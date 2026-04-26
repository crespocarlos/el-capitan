#!/usr/bin/env python3
"""
el-capitan reviewer eval harness.

Measures whether reviewer personas produce correct, well-scoped findings
when given known-bad diffs. Uses golden fixtures with annotated expected
findings to compute per-persona precision/recall.

Usage:
  uv run python evals/reviewer/run.py                              # all fixtures, all personas
  uv run python evals/reviewer/run.py --persona reviewer-adversarial
  uv run python evals/reviewer/run.py --fixture r1
  uv run python evals/reviewer/run.py --summarize                  # no API calls

Requires: OPENROUTER_API_KEY env var
Results written to: evals/reviewer/results/<timestamp>/<fixture_id>/<persona>.json
"""

import argparse
import json
import os
import pathlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional, Tuple

try:
    import openai
except ImportError:
    sys.exit("openai not installed — run: uv sync")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = pathlib.Path(__file__).parent
_REPO_ROOT = _THIS_DIR.parent.parent
_AGENTS_DIR = _REPO_ROOT / ".cursor" / "agents"
_FIXTURES_PATH = _THIS_DIR / "fixtures.json"
_RESULTS_ROOT = _THIS_DIR / "results"

# ---------------------------------------------------------------------------
# Personas — all reviewer persona files present in the agents dir
# ---------------------------------------------------------------------------

REVIEWER_PERSONAS = [
    "reviewer-adversarial",
    "reviewer-architecture",
    "reviewer-code-quality",
    "reviewer-fresh-eyes",
    "reviewer-product-flow",
    "reviewer-prompt-quality",
]

# Scope violation denylist: only applied when persona is reviewer-code-quality
# Use specific architecture-lane terms; avoid bare words that appear in testing language
# (e.g. "boundary" alone matches "boundary values" — use "module boundary" instead).
SCOPE_VIOLATION_DENYLIST = [
    "architecture",
    "module boundary",
    "layer boundary",
    "service boundary",
    "domain boundary",
    "coupling",
    "dependency direction",
]

# OpenRouter free-tier models: pricing is $0 — cost estimate will be $0.00
INPUT_PRICE_PER_MTOK = 0
OUTPUT_PRICE_PER_MTOK = 0

# Default model: free tier on OpenRouter
# nemotron-3-super is #4 in programming weekly, 725B tokens/week, less congested than Google/Venice.
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Rate-limit pacing: free tier = 8 req/min → wait 8s between requests
# Requests run serially (max_workers=1) so this keeps us under the cap.
_INTER_REQUEST_DELAY = 8.0

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def load_persona_prompt(persona_name: str) -> str:
    """Read .cursor/agents/<persona_name>.md and strip YAML frontmatter."""
    path = _AGENTS_DIR / f"{persona_name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Persona file not found: {path}. "
            f"Expected one of: {', '.join(REVIEWER_PERSONAS)}"
        )
    text = path.read_text()
    # Strip YAML frontmatter between the first and second '---' delimiters
    return re.sub(r'^---\n.*?\n---\n', '', text, count=1, flags=re.DOTALL)


def load_output_rules() -> str:
    """Extract output rules block from crew-reviewer.md Step 6.

    Extracts from first occurrence of 'Produce your review now.' to the
    closing ``` of the containing fence.
    """
    path = _AGENTS_DIR / "crew-reviewer.md"
    if not path.exists():
        raise FileNotFoundError(f"crew-reviewer.md not found at {path}")
    text = path.read_text()
    match = re.search(r'(Produce your review now\..*?)^```', text, re.DOTALL | re.MULTILINE)
    if not match:
        raise ValueError("Could not extract output rules block from crew-reviewer.md")
    return match.group(1).strip()


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

def load_fixtures() -> list[dict]:
    return json.loads(_FIXTURES_PATH.read_text())["fixtures"]


def get_applicable_personas(fixture: dict, requested_persona: Optional[str] = None) -> list:
    """Return personas to run for a fixture.

    'Applicable' means: all personas named in any expected_findings entry,
    plus reviewer-code-quality unconditionally (for scope-violation checks).
    If requested_persona is set, intersect with that.
    """
    named = {ef["persona"] for ef in fixture.get("expected_findings", [])}
    if fixture.get("input_type", "diff") != "spec":
        named.add("reviewer-code-quality")  # always run for scope discipline check (diffs only)
    if requested_persona:
        return [requested_persona] if requested_persona in named or requested_persona == "reviewer-code-quality" else []
    return sorted(named)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_finding_match(raw_output: str, expected: dict) -> bool:
    """Check if raw_output contains a finding matching expected severity + match_hint.

    Splits by numbered finding header ('^\\d+\\.') so that label + hint within the
    same numbered finding are always in the same unit, even if separated by code fences
    or blank lines. This avoids false matches where label from one finding and hint
    from an unrelated finding happen to both appear in the output.
    """
    hint = expected["match_hint"].lower()
    severity = expected.get("severity")
    if severity is None:
        # Spec-type fixture: no label required, just check hint presence in full output
        return hint in raw_output.lower()
    label = f"[{severity.lower()}]"
    # Split on numbered list markers that start a finding (1., 2., etc.)
    units = re.split(r'(?m)^(?=\d+\.)', raw_output)
    for unit in units:
        if label in unit.lower() and hint in unit.lower():
            return True
    return False


def score_scope_violations(raw_output: str, persona_name: str) -> int:
    """Count scope violations (denylist terms in Code Quality output)."""
    if persona_name != "reviewer-code-quality":
        return 0
    text = raw_output.lower()
    return sum(1 for term in SCOPE_VIOLATION_DENYLIST if term in text)


def compute_precision_recall(
    raw_output: str,
    fixture: dict,
    persona_name: str,
) -> Tuple[Optional[float], Optional[float], list, list]:
    """Return (precision, recall, matched, unmatched_expected).

    Returns (None, None, ...) when no expected findings exist for this persona
    (pair excluded from aggregation).
    """
    expected_for_persona = [
        ef for ef in fixture.get("expected_findings", [])
        if ef["persona"] == persona_name
    ]
    if not expected_for_persona:
        return None, None, [], []

    matched = []
    unmatched = []
    for ef in expected_for_persona:
        if score_finding_match(raw_output, ef):
            matched.append(ef)
        else:
            unmatched.append(ef)

    recall = len(matched) / len(expected_for_persona)

    # Spec-type fixtures (severity=None): precision is not meaningful — skip it
    if all(ef.get("severity") is None for ef in expected_for_persona):
        return None, recall, matched, unmatched

    # Precision: of all label occurrences in output, how many correspond to expected findings
    # Simple heuristic: count [blocking]/[attention]/[needs more info]/[nit] labels in output
    label_count = len(re.findall(r'\[(blocking|attention|needs more info|nit)\]', raw_output, re.IGNORECASE))
    if label_count == 0:
        precision = 1.0 if not expected_for_persona else 0.0
    else:
        precision = min(len(matched), label_count) / label_count

    return precision, recall, matched, unmatched


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def run_fixture(
    client: "openai.OpenAI",
    fixture: dict,
    persona_name: str,
    output_rules: str,
    persona_prompt: str,
) -> dict:
    """Run a single persona against a single fixture and return scored results."""
    input_type = fixture.get("input_type", "diff")
    if input_type == "spec":
        dispatch_prompt = (
            "## Critique context\n\n"
            "You are reviewing a SPEC.md draft. Apply your persona's focus areas to this spec.\n\n"
            "## Spec content\n\n"
            f"{fixture['content']}\n"
        )
    else:
        dispatch_prompt = (
            "## Review context\n\n"
            "You are reviewing a code diff. Assess it according to your persona's focus areas.\n\n"
            "## Source material\n\n"
            f"```diff\n{fixture['diff']}\n```\n\n---\n\n{output_rules}\n"
        )

    t_start = time.monotonic()
    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=client._model,  # type: ignore[attr-defined]
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": persona_prompt},
                    {"role": "user", "content": dispatch_prompt},
                ],
            )
            break
        except openai.RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            wait = 65  # flat: just past the 1-min reset window
            print(f" [429 rate limit, waiting {wait}s before retry {attempt + 1}/{max_retries - 1}]", flush=True)
            time.sleep(wait)
    # Pace requests to stay under the 8 req/min free-tier limit.
    time.sleep(_INTER_REQUEST_DELAY)
    elapsed = time.monotonic() - t_start

    raw_output = response.choices[0].message.content or "" if response.choices else ""

    truncated = len(raw_output.strip()) < 50

    scope_violations = score_scope_violations(raw_output, persona_name)
    precision, recall, matched, unmatched_expected = compute_precision_recall(
        raw_output, fixture, persona_name
    )

    # unexpected_produced: findings that don't match any expected finding
    label_count = len(re.findall(r'\[(blocking|attention|needs more info|nit)\]', raw_output, re.IGNORECASE))
    unexpected_produced = max(0, label_count - len(matched))

    return {
        "fixture_id": fixture["id"],
        "persona": persona_name,
        "precision": precision,
        "recall": recall,
        "scope_violations": scope_violations,
        "truncated": truncated,
        "matched": matched,
        "unmatched_expected": unmatched_expected,
        "unexpected_produced": unexpected_produced,
        "input_tokens": response.usage.prompt_tokens if response.usage else 0,
        "output_tokens": response.usage.completion_tokens if response.usage else 0,
        "elapsed_s": round(elapsed, 2),
        "raw_output": raw_output,
    }


# ---------------------------------------------------------------------------
# Results persistence
# ---------------------------------------------------------------------------

def write_results(
    run_dir: pathlib.Path,
    fixture_id: str,
    persona_name: str,
    result: dict,
) -> None:
    out_dir = run_dir / fixture_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{persona_name}.json").write_text(json.dumps(result, indent=2))


def write_manifest(
    run_dir: pathlib.Path,
    fixture_ids: list[str],
    personas: list[str],
    all_results: list[dict],
) -> None:
    total_input = sum(r["input_tokens"] for r in all_results)
    total_output = sum(r["output_tokens"] for r in all_results)
    # Rough cost estimate: claude-opus-4-5 pricing (see OPUS_*_PRICE_PER_MTOK constants)
    cost_approx = (total_input * INPUT_PRICE_PER_MTOK + total_output * OUTPUT_PRICE_PER_MTOK) / 1_000_000
    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "fixtures": fixture_ids,
        "personas": personas,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd_approx": round(cost_approx, 4),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
# Summary + baseline comparison
# ---------------------------------------------------------------------------

_BASELINE_PATH = _FIXTURES_PATH.parent / "baseline.json"


def _compute_persona_stats(run_dir: pathlib.Path) -> dict[str, dict]:
    """Aggregate per-persona metrics from a run directory."""
    stats: dict[str, dict] = {}
    for fixture_dir in sorted(d for d in run_dir.iterdir() if d.is_dir()):
        for result_file in sorted(fixture_dir.glob("*.json")):
            r = json.loads(result_file.read_text())
            persona = r["persona"]
            if persona not in stats:
                stats[persona] = {
                    "fixtures_run": 0,
                    "precision_sum": 0.0,
                    "recall_sum": 0.0,
                    "scope_violations": 0,
                    "truncated": 0,
                    "has_precision": False,
                }
            s = stats[persona]
            if not r.get("truncated"):
                if r["precision"] is not None:
                    s["fixtures_run"] += 1
                    s["precision_sum"] += r["precision"]
                    s["recall_sum"] += r["recall"]
                    s["has_precision"] = True
                elif r["recall"] is not None:
                    # spec-type fixture: precision is None, but recall is still meaningful
                    s["fixtures_run"] += 1
                    s["recall_sum"] += r["recall"]
            else:
                s["truncated"] += 1
            s["scope_violations"] += r.get("scope_violations", 0)
    return stats


def save_baseline(run_dir: pathlib.Path, model: str) -> None:
    """Write per-persona summary metrics from run_dir to baseline.json."""
    stats = _compute_persona_stats(run_dir)
    manifest_path = run_dir / "manifest.json"
    run_at = json.loads(manifest_path.read_text()).get("run_at", "") if manifest_path.exists() else ""
    out: dict = {"model": model, "run_at": run_at, "personas": {}}
    for persona, s in stats.items():
        n = s["fixtures_run"]
        entry: dict = {
            "recall": round(s["recall_sum"] / n, 4) if n else 0.0,
            "scope_violations": s["scope_violations"],
            "fixtures_scored": n,
        }
        if s["has_precision"]:
            entry["precision"] = round(s["precision_sum"] / n, 4) if n else 0.0
        out["personas"][persona] = entry
    _BASELINE_PATH.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Baseline saved to {_BASELINE_PATH}")


def compare_to_baseline(persona_stats: dict[str, dict]) -> bool:
    """Print delta table vs baseline.json if it exists. Returns True if any regression found."""
    if not _BASELINE_PATH.exists():
        return False
    baseline = json.loads(_BASELINE_PATH.read_text())
    b_personas = baseline.get("personas", {})
    b_model = baseline.get("model", "unknown")
    b_run_at = baseline.get("run_at", "")
    print(f"\n=== vs baseline ({b_model} @ {b_run_at}) ===")
    col_w = 28
    print(f"{'persona':<{col_w}} {'recall Δ':>10} {'precision Δ':>13} {'violations Δ':>14}")
    print("-" * (col_w + 42))
    has_regression = False
    for persona in sorted(set(list(persona_stats) + list(b_personas))):
        s = persona_stats.get(persona)
        b = b_personas.get(persona)
        if s is None or b is None:
            status = "(new)" if b is None else "(missing)"
            print(f"{persona:<{col_w}} {status}")
            continue
        n = s["fixtures_run"]
        cur_r = s["recall_sum"] / n if n else float("nan")
        cur_p = s["precision_sum"] / n if n and s["has_precision"] else float("nan")
        b_recall = b.get("recall", 0.0)
        b_precision = b.get("precision")
        delta_r = cur_r - b_recall
        delta_p = (cur_p - b_precision) if b_precision is not None and cur_p == cur_p else float("nan")
        delta_v = s["scope_violations"] - b["scope_violations"]
        r_str = f"{delta_r:+.2f}"
        p_str = f"{delta_p:+.2f}" if delta_p == delta_p else "n/a"
        v_str = f"{delta_v:+d}" if delta_v != 0 else "0"
        precision_regression = (
            s["has_precision"]
            and b_precision is not None
            and delta_p == delta_p  # not nan
            and delta_p < -0.20
        )
        flag = " *** REGRESSION ***" if delta_r < -0.05 or delta_v > 0 or precision_regression else ""
        if flag:
            has_regression = True
        print(f"{persona:<{col_w}} {r_str:>10} {p_str:>13} {v_str:>14}{flag}")
    if has_regression:
        print("\nFAIL: regressions detected (see *** REGRESSION *** rows above)")
    print()
    return has_regression


def summarize(results_root: pathlib.Path, compare: bool = False) -> int:
    """Print summary of most recent run. Returns exit code (1 if violations found)."""
    runs = sorted(
        (d for d in results_root.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    ) if results_root.exists() else []

    if not runs:
        print("No results found.")
        return 0

    latest = runs[0]
    manifest_path = latest / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    print(f"\n=== Reviewer Eval Summary: {latest.name} ===\n")
    if manifest:
        print(f"Fixtures: {manifest.get('fixtures', [])}  Personas: {manifest.get('personas', [])}")
        print(f"Cost (approx): ${manifest.get('total_cost_usd_approx', 0):.4f}\n")

    # Aggregate per persona
    persona_stats = _compute_persona_stats(latest)
    has_violations = False

    # Print table
    col_w = 28
    print(f"{'persona':<{col_w}} {'scored':>8} {'precision':>10} {'recall':>8} {'violations':>11}")
    print("-" * (col_w + 42))

    exit_code = 0
    for persona, s in sorted(persona_stats.items()):
        n = s["fixtures_run"]
        avg_p = s["precision_sum"] / n if n > 0 and s["has_precision"] else float("nan")
        avg_r = s["recall_sum"] / n if n > 0 else float("nan")
        viol = s["scope_violations"]
        trunc = s["truncated"]
        trunc_note = f" ({trunc} truncated)" if trunc else ""
        viol_str = f"{viol} *** FAIL ***" if viol > 0 else str(viol)
        p_str = f"{avg_p:>9.2f}" if avg_p == avg_p else f"{'n/a':>9}"  # nan check
        if viol > 0:
            has_violations = True
            exit_code = 1
        print(
            f"{persona:<{col_w}} {n:>8}{trunc_note}  "
            f"{p_str}  {avg_r:>7.2f}  {viol_str:>11}"
        )

    if has_violations:
        print("\nFAIL: scope violations detected (see *** FAIL *** rows above)")

    if compare:
        if compare_to_baseline(persona_stats):
            exit_code = 1
    else:
        print()
    return exit_code


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="el-capitan reviewer eval harness")
    parser.add_argument("--persona", help="Run only this persona (e.g. reviewer-adversarial)")
    parser.add_argument("--fixture", help="Run only this fixture ID (e.g. r1)")
    parser.add_argument("--arms", help="(unused, for CLI consistency)")
    parser.add_argument(
        "--summarize", action="store_true",
        help="Print summary of most recent results without API calls"
    )
    parser.add_argument(
        "--save-baseline", action="store_true",
        help="Save most recent run as baseline.json for future comparison"
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="After running, print delta vs baseline.json"
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Model name to use and record in baseline (default: {DEFAULT_MODEL})"
    )
    args = parser.parse_args()

    _RESULTS_ROOT.mkdir(exist_ok=True)

    if args.summarize:
        sys.exit(summarize(_RESULTS_ROOT, compare=args.compare))

    if args.save_baseline:
        runs = sorted(
            (d for d in _RESULTS_ROOT.iterdir() if d.is_dir()),
            key=lambda d: d.name, reverse=True,
        ) if _RESULTS_ROOT.exists() else []
        if not runs:
            sys.exit("No results to save as baseline.")
        save_baseline(runs[0], model=args.model)
        sys.exit(0)

    # Run mode: run evals (requires API key)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY not set")

    model = args.model
    client = openai.OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
    client._model = model  # type: ignore[attr-defined]

    output_rules = load_output_rules()
    fixtures = load_fixtures()

    if args.fixture:
        fixtures = [f for f in fixtures if f["id"] == args.fixture]
        if not fixtures:
            sys.exit(f"Fixture '{args.fixture}' not found in fixtures.json")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = _RESULTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[dict] = []
    all_personas: set[str] = set()
    all_fixture_ids: list[str] = []

    # Build work items
    work_items = []
    for fixture in fixtures:
        personas = get_applicable_personas(fixture, args.persona)
        for persona_name in personas:
            work_items.append((fixture, persona_name))
        all_fixture_ids.append(fixture["id"])

    total = len(work_items)
    print(f"Run: {run_id}")
    print(f"Fixtures: {[f['id'] for f in fixtures]}  Work items: {total}\n")

    def _run_one(item: tuple) -> dict:
        fixture, persona_name = item
        persona_prompt = load_persona_prompt(persona_name)
        print(f"  [{fixture['id']}] persona={persona_name} ...", end="", flush=True)
        result = run_fixture(client, fixture, persona_name, output_rules, persona_prompt)
        write_results(run_dir, fixture["id"], persona_name, result)
        print(
            f" recall={result['recall']:.2f} precision={result['precision']:.2f}"
            f" violations={result['scope_violations']}"
            f" ({result['elapsed_s']}s)"
            if result["precision"] is not None
            else f" (no expected findings for this persona) violations={result['scope_violations']} ({result['elapsed_s']}s)"
        )
        return result

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(_run_one, item): item for item in work_items}
        for future in as_completed(futures):
            try:
                result = future.result()
                all_results.append(result)
                all_personas.add(result["persona"])
            except Exception as exc:
                fixture, persona_name = futures[future]
                print(f"  ERROR [{fixture['id']}] {persona_name}: {exc}", file=sys.stderr)

    if not all_results:
        print("\nFAIL: no results produced — all fixtures errored", file=sys.stderr)
        sys.exit(1)

    write_manifest(run_dir, all_fixture_ids, sorted(all_personas), all_results)
    print(f"\nResults written to: {run_dir}")
    sys.exit(summarize(_RESULTS_ROOT, compare=args.compare))


if __name__ == "__main__":
    main()
