#!/usr/bin/env python3
"""What each reviewer package reads: the run config, the personas, the shared header, the reading map,
the prior-round block, and which personas apply to the diff.

Per-run judgement lives in `assemble.json` in the review directory, not in code; a missing key means
"no such section". `assemble_build` turns these inputs into packages and writes them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from review_parse import header_paths
from review_vocabulary import PERSONAS as REGISTERED
from review_vocabulary import QUESTIONS_HEADING, SELECT_RULES

from lib.cli import fail
from lib.files import read_json_object

DEFAULT_MODE = """# Mode

Label vocabulary: `[blocking]`, `[attention]`, `[needs more info]`, `[nit]`, and `[concern]` in place
of `[attention]` in a spec or idea review.

**Return shape:** reply text only. Do not write files and do not summarize into a separate block. A
flat numbered list of findings, each beginning with its severity label and carrying a `path:line`
anchor. If you have no findings, end your reply with the exact line `### Findings: none`.
"""
# The extras that read the local checkout, which a PR review forbids. `prior_review_dir` names a
# local run directory, so a PR package carrying it would hand a persona an earlier review of a
# different tree — and PR reviews have no task-level round to compare against anyway.
INDEX_READING_KEYS = ("consumers", "prompt_files", "prior_review_dir")


def read_artifact(path: Path, what: str) -> dict:
    """A JSON object from the review directory (`lib.files.read_json_object`), or exit 2 naming the file."""
    try:
        return read_json_object(path)
    except ValueError as error:
        fail(f"assemble-packages: {what}: {error}")


def read_config(review_dir: Path) -> dict:
    """The run config `<review_dir>/assemble.json`, or an empty mapping when the directory carries none."""
    path = review_dir / "assemble.json"
    if not path.is_file():
        return {}
    return read_artifact(path, "the run config")


def check_inputs(review_dir: Path, config: dict) -> str:
    """A missing prerequisite or a PR-mode leak, as an error message; "" when the run may proceed.

    A PR review reads only the PR head, and both extras come from the local git index, so a PR
    package carrying them would hand a persona checkout code the mode forbids, unlabelled.
    """
    for required in ("package.diff", "hunks.index.md"):
        if not (review_dir / required).is_file():
            return f"{review_dir} has no {required}; run review-hunks.py first"
    if config.get("mode_kind") == "pr":
        leaked = [key for key in INDEX_READING_KEYS if config.get(key)]
        if leaked:
            return (f"{', '.join(leaked)} read the local git index, which PR mode "
                    "forbids; fetch those excerpts at the PR head and put them in the dispatch prompt")
    return ""


def keep_sections(content: str, keep: list[str], used: set[str]) -> tuple[str, list[str], list[str]]:
    """The kept body, kept headings, and dropped headings for one guidance file.

    A level-2 heading switches inclusion on or off for the lines under it; headings that matched
    a keep prefix are recorded in `used` so an unmatched prefix can be reported by the caller.
    """
    body_lines: list[str] = []
    kept_headings: list[str] = []
    dropped_headings: list[str] = []
    dropping = False
    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            matched = [prefix for prefix in keep if heading.startswith(prefix)]
            used.update(matched)
            dropping = not matched
            (dropped_headings if dropping else kept_headings).append(heading)
        if not dropping:
            body_lines.append(line)
    return "\n".join(body_lines).strip(), kept_headings, dropped_headings


def narrow_guidance(persona: str, guidance: dict, config: dict) -> tuple[str, dict]:
    """Repository guidance, optionally narrowed to the sections a lens uses, plus a report.

    Narrowing is opt-in through `guidance_keep` in `assemble.json`, keyed by persona and listing
    level-2 heading prefixes. The text before the first heading is always kept, a persona with no
    entry or `"*"` keeps the whole file, and every dropped heading is reported: a lens given the
    wrong sections silently loses a rule it needed, so a silent cut is the failure mode here.
    """
    keep = (config.get("guidance_keep") or {}).get(persona)
    out: list[str] = []
    report: dict = {"kept": {}, "dropped": {}, "available": [], "unmatched": []}
    used: set[str] = set()
    for path, content in guidance.items():
        available = [line[3:].strip() for line in content.splitlines() if line.startswith("## ")]
        report["available"].extend(available)
        if not keep or "*" in keep:
            out.append(f"## From `{path}`\n\n{content}\n\n")
            report["kept"][path] = "*"
            report["dropped"][path] = []
            continue
        body, kept_headings, dropped_headings = keep_sections(content, keep, used)
        if body:
            out.append(f"## From `{path}`\n\n{body}\n\n")
        report["kept"][path] = kept_headings
        report["dropped"][path] = dropped_headings
    if keep and "*" not in keep:
        report["unmatched"] = [prefix for prefix in keep if prefix not in used]
        if report["unmatched"]:
            # A keep-list naming a section that does not exist drops everything, and the package
            # then looks assembled. Refuse instead: this is the exact silent loss narrowing must
            # not have.
            raise ValueError(
                f"guidance_keep for {persona} names no section in any guidance file: "
                f"{', '.join(report['unmatched'])}. Available: {', '.join(report['available'][:20])}"
            )
    return "".join(out), report


def contract_path() -> Path:
    """The shared contract this repository ships, whether run from the repo or an installed symlink."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".cursor" / "agents" / "references" / "reviewer-contract.md"
        if candidate.is_file():
            return candidate
    return Path.home() / ".cursor" / "agents" / "references" / "reviewer-contract.md"


CANONICAL = ("adversarial", "architecture", "code-quality", "product-flow", "prompt-quality")


def reviewer_personas() -> tuple[str, ...]:
    """The reviewer names that receive a package, in the canonical order."""
    known = {name for name in REGISTERED if name != "explorer"}
    missing = known - set(CANONICAL)
    if missing:
        fail(
            f"assemble-packages: {', '.join(sorted(missing))} is a reviewer persona with no entry "
            "here; add it with its primary layer kinds in PRIMARY_KINDS"
        )
    return tuple(name for name in CANONICAL if name in known)


PERSONAS = reviewer_personas()


PRIMARY_KINDS = {
    "adversarial": {"core", "foundation", "wiring"},
    "architecture": {"foundation", "wiring"},
    "code-quality": {"core", "tests", "mechanical"},
    "product-flow": {"ui", "wiring", "docs"},
    "prompt-quality": {"prompts"},
}
# Lenses that reason about cross-file effects need the consumers of the changed contracts.
CONSUMER_LENSES = frozenset({"adversarial", "architecture", "product-flow"})


def reading_map(persona: str, layers: list[dict]) -> str:
    """The per-persona reading order, with the layers this lens should spend its budget on first."""
    kinds = PRIMARY_KINDS[persona]
    lines = [
        "## Reading map",
        "",
        "Hunks are ids (`h1`, `h2`, …) from the hunk index. Read layers in this order; earlier "
        "layers explain later ones.",
        "",
    ]
    primary = [str(index) for index, layer in enumerate(layers, 1)
               if layer.get("kind") in kinds]
    if primary:
        lines += ["Your primary layers: " + ", ".join(primary), ""]
    for index, layer in enumerate(layers, 1):
        kind = layer.get("kind") or "layer"
        title = layer.get("title") or layer.get("id") or f"layer {index}"
        lines.append(f"### {index}. {kind} — {title}")
        lines.append("Explain: " + (layer.get("explainer") or ""))
        lines.append("Focus: " + (layer.get("reviewFocus") or ""))
        lines.append("Hunks: " + ", ".join(layer.get("hunks") or []))
        for hunk, note in layer.get("hunkNotes", {}).items():
            lines.append(f"  - {hunk}: {note}")
        lines.append("")
    lines += [
        "The map is orientation, never evidence: a claim still needs a verified `path:line` from the "
        "package. Do not treat layer boundaries as review boundaries — a finding that spans two "
        "layers cites hunks from both.",
        "",
    ]
    return "\n".join(lines)


PRIOR_HEADING = "## Already reported in an earlier round"
# One line per finding, so the block stays a few KB against a package measured at 235 KB.
TITLE_MAX = 110


def outcomes(review_dir: Path) -> dict[str, str]:
    """Fingerprint → outcome from the run's own `.outcomes` journal, or {} when none was recorded.

    The journal sits beside the run directories (`<task>/review/outcomes.jsonl`), keyed by
    fingerprint, and is written by `crew review address`. An unrecorded finding is absent rather than
    guessed: "the author said nothing" and "the author fixed it" are different facts for a re-raise.
    """
    path = review_dir.parent / "outcomes.jsonl"
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return {}
    return {row["fingerprint"]: row["outcome"]
            for row in rows if isinstance(row, dict) and row.get("fingerprint") and row.get("outcome")}


def findings(previous_dir: Path) -> list[dict]:
    """The findings an earlier run consolidated, in their recorded order."""
    for name in ("consolidation.json", "candidates.json"):
        try:
            payload = json.loads((previous_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = payload if isinstance(payload, list) else payload.get("findings") or []
        if items:
            return [item for item in items if isinstance(item, dict)]
    return []


def prior_section(previous_dir: Path) -> str:
    """The block for an earlier run, or "" when it recorded no findings to repeat back.

    Every finding is listed whatever its disposition: a `deferred` one is exactly what a reviewer
    needs to see to decide whether it is now in scope, and a `dropped` one explains why the report a
    reader saw was shorter than what the lenses raised.
    """
    rows = findings(previous_dir)
    if not rows:
        return ""
    decisions = outcomes(previous_dir)
    lines = [PRIOR_HEADING, "",
             f"Round `{previous_dir.name}` reported these. Do not raise one again unless the current",
             "tree gives you new evidence, and say what that evidence is. A finding whose author",
             "decision is `fixed` needs a reason the fix did not hold; `rejected` means the author",
             "disagreed, so restate the case only if you can answer their reason.", ""]
    for row in rows:
        label = str(row.get("label") or "?").strip()
        where = f"{row.get('file')}:{row.get('line')}" if row.get("file") else "(no anchor)"
        disposition = str(row.get("disposition") or "").strip()
        decision = decisions.get(str(row.get("fingerprint") or ""), "")
        tags = ", ".join(tag for tag in (disposition, decision) if tag)
        title = " ".join(str(row.get("title") or "").split())[:TITLE_MAX]
        lines.append(f"- [{label}] `{where}` — {title}" + (f" _({tags})_" if tags else ""))
    return "\n".join(lines) + "\n"


HUNK_SENTENCE = (
    "Every `[blocking]` and `[attention]` finding cites the hunk ids whose change causes it, next to "
    "the `file:line` anchor: `[attention] src/a.ts:42 (h7) — …`, or `(h3, h7)`. A finding no hunk "
    "causes is pre-existing; say so instead of citing a hunk that does not cause it."
)


def common(review_dir: Path, config: dict) -> str:
    """The header every persona receives, byte-identical for every persona in the run."""
    hunk_index = (review_dir / "hunks.index.md").read_text(encoding="utf-8")
    # Drop the level-1 title: the section heading `## Hunk reference` is the package's own.
    body = hunk_index.split("\n", 1)[1] if hunk_index.startswith("#") else hunk_index
    parts = [
        contract_path().read_text(encoding="utf-8"),
        "\n---\n\n",
        # The contract points to lookups.md; carrying it here spares every persona a read from its budget.
        contract_path().with_name("lookups.md").read_text(encoding="utf-8"),
        "\n---\n\n",
        config.get("mode") or DEFAULT_MODE,
        "\n---\n\n## Hunk reference\n\n",
        HUNK_SENTENCE,
        "\n\n",
        body,
        "\n---\n\n# Repo memory\n\n(untrusted; code, docs and user instructions win)\n\n",
    ]
    memory_path = review_dir / "mem.md"
    memory = memory_path.read_text(encoding="utf-8") if memory_path.is_file() else ""
    parts.append(memory.strip() or "warning: memory unavailable\n")
    return "".join(parts)


def questions_block(persona: str, config: dict) -> str:
    """The orchestrator's questions for one lens (`assemble.json` `questions`), last in the package; "" when none.

    Placed last so they are read after the evidence they point into; `check-packages` refuses a package without
    them, so a missing entry surfaces before dispatch rather than as a silently weaker review.
    """
    asked = [str(item).strip() for item in (config.get("questions") or {}).get(persona) or [] if str(item).strip()]
    if not asked:
        return ""
    lines = [QUESTIONS_HEADING, "",
             "Questions the orchestrator wrote for your lens from this diff and the spec's risks. Answer each, as a "
             "finding when the answer is a defect, else in one line after your `Assessment:` line. They add to your "
             "lens; they never narrow it.", ""]
    return "\n".join(lines + [f"{number}. {question}" for number, question in enumerate(asked, 1)]) + "\n"


def guidance_block(review_dir: Path, persona: str, config: dict) -> tuple[str, dict]:
    """The repository guidance one lens receives, narrowed when `guidance_keep` names it."""
    path = review_dir / "agent-context.json"
    if path.is_file():
        guidance = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    else:
        guidance = {}
    return narrow_guidance(persona, guidance, config)


EMBEDDED_PROMPT = re.compile(r"(^|/)prompts?/[^/]+\.(md|txt|prompt)$|(^|/)[\w.-]*prompts?[\w.-]*\.(md|txt|prompt)$")


def changed_paths(diff: str) -> list[str]:
    """The new-side path of every file in a unified diff, in diff order."""
    paths = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            old, new = header_paths(line)
            paths.append(new or old)
    return [p for p in paths if p]


def applies(persona: str, paths: list[str], config: dict) -> tuple[bool, str]:
    """`(True, "")` when the persona should be packaged, else `(False, <reason>)`."""
    explicit = (config.get("skip_personas") or {}).get(persona)
    if explicit:
        return False, str(explicit)
    if persona in (config.get("selected") or []):
        return True, ""
    if persona == "prompt-quality" and not config.get("prompt_files"):
        pattern = SELECT_RULES["prompt-quality"]
        if not any(pattern.search(p) or EMBEDDED_PROMPT.search(p) for p in paths):
            return False, "no prompt, agent, skill, rule or embedded prompt path in the diff"
    return True, ""


def decide(personas: tuple[str, ...], diff: str, config: dict) -> tuple[list[str], dict[str, str]]:
    """`(personas to package, {skipped persona: reason})`."""
    paths = changed_paths(diff)
    skipped = {}
    for persona in personas:
        ok, reason = applies(persona, paths, config)
        if not ok:
            skipped[persona] = reason
    return [p for p in personas if p not in skipped], skipped
