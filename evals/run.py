#!/usr/bin/env python3
"""
el-capitan three-arm eval harness.

Measures whether the SPEC.md template format improves structured spec output
quality vs free-form prompts, using output token count as the primary signal
and structure scoring as a secondary signal.

Arms:
  baseline   — no system prompt, raw task description only
  terse      — "be specific, list acceptance criteria" + task description
  crew-spec  — full SPEC.md template as system context + task description

Usage:
  uv run python run.py                     # run all tasks, all arms
  uv run python run.py --task t1           # run one task, all arms
  uv run python run.py --summarize         # summarize results/ only (no API calls)

Requires: ANTHROPIC_API_KEY env var
Results written to: results/<timestamp>/<task_id>/<arm>.json
"""

import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

try:
    import anthropic
except ImportError:
    sys.exit("anthropic not installed — run: uv sync")

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
except ImportError:
    def count_tokens(text: str) -> int:
        # Rough approximation when tiktoken not available
        return len(text) // 4

# ---------------------------------------------------------------------------
# Spec template (crew-spec arm system prompt)
# ---------------------------------------------------------------------------

SPEC_TEMPLATE_PATH = pathlib.Path(__file__).parent.parent / ".agent" / "_SPEC_TEMPLATE.md"

def load_spec_template() -> str:
    if SPEC_TEMPLATE_PATH.exists():
        return SPEC_TEMPLATE_PATH.read_text()
    # Fallback: minimal template
    return """You are crew-specwriter. Given a feature request, produce a SPEC.md with these sections:
# Spec: [title]
## Context — Problem, Scope (in/out), Repo touchpoints
## Goal — one sentence
## Acceptance Criteria — Requirements + Non-regression checklists
## Design Constraints — structural rules, verifiable by inspection
## Tasks — atomic, independently verifiable, each with Change/Files/Acceptance
## Tests — typed subsections (Unit, Integration, E2E, Validation)
"""

# ---------------------------------------------------------------------------
# System prompts per arm
# ---------------------------------------------------------------------------

ARMS = {
    "baseline": None,  # no system prompt
    "terse": (
        "You are a software engineering assistant. "
        "Respond specifically and thoroughly. "
        "Always list acceptance criteria explicitly as checkboxes. "
        "No prose filler."
    ),
    "crew-spec": None,  # loaded from template at runtime
}

USER_PROMPT_TEMPLATE = """\
Draft a SPEC.md for the following feature request:

{description}

Produce the full spec document. Be thorough and complete."""

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

STRUCTURE_KEYS = [
    "## Context",
    "## Goal",
    "## Acceptance Criteria",
    "## Design Constraints",
    "## Tasks",
    "## Tests",
    "- [ ]",          # checklist items
    "**Acceptance**",  # task acceptance blocks
]

def score_structure(text: str) -> dict:
    """Return presence scores for expected SPEC.md structural elements."""
    scores = {}
    for key in STRUCTURE_KEYS:
        scores[key] = 1 if key in text else 0
    scores["total"] = sum(scores.values())
    scores["max"] = len(STRUCTURE_KEYS)
    return scores

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_arm(client: anthropic.Anthropic, arm_name: str, system_prompt: str | None,
            task: dict) -> dict:
    user_msg = USER_PROMPT_TEMPLATE.format(description=task["description"])
    messages = [{"role": "user", "content": user_msg}]

    kwargs: dict = {
        "model": "claude-opus-4-5",
        "max_tokens": 4096,
        "messages": messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    t_start = time.monotonic()
    response = client.messages.create(**kwargs)
    elapsed = time.monotonic() - t_start

    content = next((b.text for b in response.content if hasattr(b, "text")), "") if response.content else ""
    usage = response.usage

    return {
        "arm": arm_name,
        "task_id": task["id"],
        "model": response.model,
        "input_tokens_api": usage.input_tokens,
        "output_tokens_api": usage.output_tokens,
        "output_tokens_tiktoken": count_tokens(content),
        "elapsed_s": round(elapsed, 2),
        "structure_score": score_structure(content),
        "output": content,
        "system_prompt_tokens": count_tokens(system_prompt) if system_prompt else 0,
    }


def run_task(client: anthropic.Anthropic, task: dict, arms: list[str],
             results_dir: pathlib.Path) -> list[dict]:
    task_dir = results_dir / task["id"]
    task_dir.mkdir(parents=True, exist_ok=True)

    spec_template = load_spec_template()
    arm_prompts = {
        "baseline": None,
        "terse": ARMS["terse"],
        "crew-spec": spec_template,
    }

    results = []
    for arm_name in arms:
        if arm_name not in arm_prompts:
            print(f"  Unknown arm: {arm_name}", file=sys.stderr)
            continue

        print(f"  [{task['id']}] arm={arm_name} ...", end="", flush=True)
        result = run_arm(client, arm_name, arm_prompts[arm_name], task)
        out_file = task_dir / f"{arm_name}.json"
        out_file.write_text(json.dumps(result, indent=2))
        print(f" {result['output_tokens_api']} tokens ({result['elapsed_s']}s)")
        results.append(result)

    return results


def summarize(results_root: pathlib.Path) -> None:
    runs = sorted(results_root.iterdir(), reverse=True)
    if not runs:
        print("No results found.")
        return

    latest = runs[0]
    print(f"\n=== Summary: {latest.name} ===\n")
    print(f"{'task':<6} {'arm':<12} {'out_tokens':>10} {'struct':>8} {'input_tok':>10}")
    print("-" * 52)

    all_results = []
    for task_dir in sorted(d for d in latest.iterdir() if d.is_dir()):
        for arm_file in sorted(task_dir.glob("*.json")):
            r = json.loads(arm_file.read_text())
            all_results.append(r)
            struct = f"{r['structure_score']['total']}/{r['structure_score']['max']}"
            print(f"{r['task_id']:<6} {r['arm']:<12} {r['output_tokens_api']:>10} {struct:>8} {r['input_tokens_api']:>10}")

    print()
    # Per-arm averages
    for arm in ["baseline", "terse", "crew-spec"]:
        arm_results = [r for r in all_results if r["arm"] == arm]
        if not arm_results:
            continue
        avg_out = sum(r["output_tokens_api"] for r in arm_results) / len(arm_results)
        avg_struct = sum(r["structure_score"]["total"] for r in arm_results) / len(arm_results)
        print(f"  {arm:<12} avg_output={avg_out:.0f}  avg_structure={avg_struct:.1f}/{arm_results[0]['structure_score']['max']}")

    print()
    # Delta: crew-spec vs baseline
    baseline = {r["task_id"]: r for r in all_results if r["arm"] == "baseline"}
    crew_spec = {r["task_id"]: r for r in all_results if r["arm"] == "crew-spec"}
    if baseline and crew_spec:
        common = set(baseline) & set(crew_spec)
        deltas_tok = [crew_spec[t]["output_tokens_api"] - baseline[t]["output_tokens_api"] for t in common]
        deltas_struct = [crew_spec[t]["structure_score"]["total"] - baseline[t]["structure_score"]["total"] for t in common]
        avg_tok_delta = sum(deltas_tok) / len(deltas_tok)
        avg_struct_delta = sum(deltas_struct) / len(deltas_struct)
        print(f"  crew-spec vs baseline: output_tokens Δ={avg_tok_delta:+.0f}  structure Δ={avg_struct_delta:+.1f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="el-capitan three-arm eval harness")
    parser.add_argument("--task", help="Run only this task ID (e.g. t1)")
    parser.add_argument("--arms", default="baseline,terse,crew-spec",
                        help="Comma-separated arms to run (default: all three)")
    parser.add_argument("--summarize", action="store_true",
                        help="Summarize existing results without running new evals")
    args = parser.parse_args()

    results_root = pathlib.Path(__file__).parent / "results"
    results_root.mkdir(exist_ok=True)

    if args.summarize:
        summarize(results_root)
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)

    tasks_file = pathlib.Path(__file__).parent / "tasks.json"
    tasks_data = json.loads(tasks_file.read_text())
    tasks = tasks_data["tasks"]

    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]
        if not tasks:
            sys.exit(f"Task '{args.task}' not found in tasks.json")

    arms = [a.strip() for a in args.arms.split(",")]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results_dir = results_root / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"Run: {run_id}")
    print(f"Tasks: {[t['id'] for t in tasks]}  Arms: {arms}\n")

    all_results = []
    for task in tasks:
        results = run_task(client, task, arms, results_dir)
        all_results.extend(results)

    # Write run manifest
    manifest = {
        "run_id": run_id,
        "tasks": [t["id"] for t in tasks],
        "arms": arms,
        "total_output_tokens": sum(r["output_tokens_api"] for r in all_results),
        "total_input_tokens": sum(r["input_tokens_api"] for r in all_results),
    }
    (results_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"\nResults written to: {results_dir}")
    summarize(results_root)


if __name__ == "__main__":
    main()
