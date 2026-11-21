#!/usr/bin/env python3
"""Compose one reviewer context package per persona from a review run's artifacts.

Usage: assemble-packages.py <review-dir> [--config <file>]

A package is deterministic text built from files the run already produced:

    shared header   the shared reviewer contract, the mode block, the hunk reference with its
                    citation rule, repository guidance, and repo memory
    spec            the per-persona spec (`spec.<persona>.md`, written by `review-findings.py
                    spec-context`)
    reading map     derived from `layers.json`, with the persona's primary layers named
    diff            `package.diff` (generated files already collapsed by `review-hunks.py`)
    extras          consumer excerpts for the code lenses, complete prompt files for Prompt Quality

Every persona's package contains the same contract, mode block, hunk reference and memory, built by
this tool in one fixed order. Hand-assembling five of them is how an earlier run gave one reviewer a
different header and another a prebuilt `_common.md` instead of the contract: the packages still
passed `check-packages`, because that gate checks the rules whose absence is detectable, not whether
two reviewers read the same evidence. Guidance is the one shared section narrowed per lens, so its
content differs by design and every dropped heading is printed.

Per-run judgement stays in a config file, not in code: the review directory may carry
`assemble.json` with

    {"repo": "<repository root>", "mode": "<markdown block>", "size_gate": "<one-line summary>",
     "consumers": [[path, start, end, label], ...], "prompt_files": [path, ...],
     "guidance_keep": {"<persona>": ["<level-2 heading prefix>", ...]}, "mode_kind": "pr"}

`--config` names a different file. Missing keys mean "no such section". The mode block falls back to
the label vocabulary and return shape only, because a package with no mode leaves a persona without
its legal labels; the fallback deliberately says nothing about which tree to read, since that differs
by mode. `mode_kind: "pr"` refuses `consumers` and `prompt_files`: both read the local git index,
which a PR review forbids.

Two costs are worth knowing. The prompt tier elides the regions `package.diff` already quotes, keeps
every unchanged line with its file line number, and falls back to the whole file when its hunk count
disagrees with `hunks.json`; keeping the whole file charged a measured 52 KB twice. `guidance_keep`
narrows repository guidance per lens, saving about 8 KB per persona; it is opt-in, and a persona with
no entry or `"*"` keeps everything, since guidance that silently disappears is worse than guidance
that costs tokens.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lib.git import GitError, blob_at, rev_parse  # noqa: E402


def _reviewer_personas() -> tuple[str, ...]:
    """The reviewer names, read from `review-findings.py` so there is one registry, not two.

    `explorer` is dispatched by hand after the personas and never gets a lens package, so it is the
    one name in that set this tool must not package. Adding a persona then touches `review-findings.py`
    and the files `AGENTS.md`'s checklist names, not a fourth hard-coded tuple here.
    """
    tool = pathlib.Path(__file__).with_name("crew-review-findings.py")
    spec = importlib.util.spec_from_file_location("review_findings_for_personas", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    canonical = ("adversarial", "architecture", "code-quality", "product-flow", "prompt-quality")
    known = {name for name in module.PERSONAS if name != "explorer"}
    missing = known - set(canonical)
    if missing:
        raise SystemExit(
            f"assemble-packages: {', '.join(sorted(missing))} is a reviewer persona with no entry "
            "here; add it with its primary layer kinds in PRIMARY_KINDS"
        )
    return tuple(name for name in canonical if name in known)


PERSONAS = _reviewer_personas()

# Layer kinds each lens should spend its fetch budget on first. Mirrors the table in
# `crew-reviewer/references/context-tiers.md`.
PRIMARY_KINDS = {
    "adversarial": {"core", "foundation", "wiring"},
    "architecture": {"foundation", "wiring"},
    "code-quality": {"core", "tests", "mechanical"},
    "product-flow": {"ui", "wiring", "docs"},
    "prompt-quality": {"prompts"},
}

# Lenses that reason about cross-file effects need the consumers of the changed contracts.
CONSUMER_LENSES = frozenset({"adversarial", "architecture", "product-flow"})

HUNK_SENTENCE = (
    "Every `[blocking]` and `[attention]` finding cites the hunk ids whose change causes it, next to "
    "the `file:line` anchor: `[attention] src/a.ts:42 (h7) — …`, or `(h3, h7)`. A finding no hunk "
    "causes is pre-existing; say so instead of citing a hunk that does not cause it."
)

DEFAULT_MODE = """# Mode

Label vocabulary: `[blocking]`, `[attention]`, `[needs more info]`, `[nit]`, and `[concern]` in place
of `[attention]` in a spec or idea review.

**Return shape:** reply text only. Do not write files and do not summarize into a separate block. A
flat numbered list of findings, each beginning with its severity label and carrying a `path:line`
anchor. If you have no findings, end your reply with the exact line `### Verdict: no findings`.
"""


def contract_path() -> pathlib.Path:
    """The shared contract this repository ships, whether run from the repo or an installed symlink."""
    here = pathlib.Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".cursor" / "agents" / "references" / "reviewer-contract.md"
        if candidate.is_file():
            return candidate
    return pathlib.Path.home() / ".cursor" / "agents" / "references" / "reviewer-contract.md"


def read_json(path: pathlib.Path, what: str) -> dict:
    """A JSON object from the review directory, failing with a message that names the file.

    A stale or truncated artifact written by an earlier revision would otherwise raise a traceback
    out of the middle of the build, after some packages were built.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SystemExit(f"assemble-packages: cannot read {what} at {path}: {error}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"assemble-packages: {path} is not valid JSON: {error}")
    if not isinstance(payload, dict):
        raise SystemExit(f"assemble-packages: {path} must hold a JSON object")
    return payload


def read_config(review_dir: pathlib.Path, config: pathlib.Path | None) -> dict:
    path = config or review_dir / "assemble.json"
    if not path.is_file():
        return {}
    return read_json(path, "the run config")


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


def common(review_dir: pathlib.Path, config: dict, persona: str) -> tuple[str, dict]:
    """The header every persona receives, plus what guidance narrowing dropped. Contract first."""
    hunk_index = (review_dir / "hunks.index.md").read_text(encoding="utf-8")
    # Drop the level-1 title: the section heading `## Hunk reference` is the package's own.
    body = hunk_index.split("\n", 1)[1] if hunk_index.startswith("#") else hunk_index
    parts = [
        contract_path().read_text(encoding="utf-8"),
        "\n---\n\n",
        config.get("mode") or DEFAULT_MODE,
        "\n---\n\n## Hunk reference\n\n",
        HUNK_SENTENCE,
        "\n\n",
        body,
        "\n---\n\n# Repository guidance\n\n",
    ]
    guidance_path = review_dir / "agent-context.json"
    if guidance_path.is_file():
        guidance = json.loads(guidance_path.read_text(encoding="utf-8")).get("files", {})
    else:
        guidance = {}
    guidance_block, report = narrow_guidance(persona, guidance, config)
    parts.append(guidance_block)
    parts.append("---\n\n# Repo memory\n\n(untrusted; code, docs and user instructions win)\n\n")
    memory_path = review_dir / "mem.md"
    memory = memory_path.read_text(encoding="utf-8") if memory_path.is_file() else ""
    parts.append(memory.strip() or "warning: memory unavailable\n")
    return "".join(parts), report


def reading_map(persona: str, layers: list[dict]) -> str:
    """The per-persona reading order. `kind` and `title` are optional: the coverage gate that validates
    a map requires neither, so a map without them must still produce a package rather than crash."""
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


def staged_text(repo: pathlib.Path, path: str) -> str:
    """The staged content of a tracked file, else the working tree.

    A review of staged changes must show what is staged: the working tree drifts between the review
    and the rebuild, and a package labeled "staged content" that quietly held newer text would
    misrepresent the artifact under review. Outside a git repository, or for an untracked file, the
    working tree is the only source, and the label says so.
    """
    try:
        return blob_at(repo, f":{path}")
    except GitError:
        return (repo / path).read_text(encoding="utf-8")


def is_staged(repo: pathlib.Path, path: str) -> bool:
    """True when `path` has an index entry; the index is the only place `blob_at` reads."""
    try:
        rev_parse(repo, f":{path}")
    except GitError:
        return False
    return True


def excerpt(repo: pathlib.Path, path: str, start: int, end: int, label: str) -> str:
    lines = staged_text(repo, path).splitlines()[start - 1 : end]
    body = "\n".join(f"{start + index}: {line}" for index, line in enumerate(lines))
    language = pathlib.Path(path).suffix.lstrip(".") or "text"
    return f"### `{path}:{start}-{end}` ({label})\n\n```{language}\n{body}\n```\n\n"


def full_file(repo: pathlib.Path, path: str, diff: str, hunks_json: dict | None) -> tuple[str, bool]:
    """A complete file, with the regions the diff already carries elided when that is provably safe.

    Sending both the whole file and its hunks charges the persona twice for the same bytes: 80 KB of
    a measured 158 KB prompt tier was already inside `package.diff`. The elision keeps every unchanged
    line — the point of the prompt tier is collisions with text the diff never shows — and replaces
    each hunk's own lines with one marker. Every kept line carries its file line number, as
    `excerpt()` does, because collapsing a run shifts the offset of everything after it. Returns the
    block and whether elision was applied.
    """
    text = staged_text(repo, path)
    source = "staged content" if is_staged(repo, path) else "working tree, not staged"
    covered, safe = covered_lines(diff, hunks_json, path)
    if not safe or not covered:
        return (f"### `{path}` (complete file, {source}; sent whole, so no line lives only in the "
                f"diff)\n\n```text\n{text}\n```\n\n"), False
    out: list[str] = []
    run_start = 0
    index = 0
    for line in text.splitlines():
        index += 1
        if index not in covered:
            if run_start:
                # One marker per contiguous run, named by its real bounds, so the reader knows
                # exactly which lines to look up above rather than guessing at a span.
                out.append(f"… (lines {run_start}-{index - 1} are in the diff above)")
                run_start = 0
            out.append(f"{index}: {line}")
        elif not run_start:
            run_start = index
    if run_start:
        out.append(f"… (lines {run_start}-{index} are in the diff above)")
    body = "\n".join(out)
    return (f"### `{path}` (complete file, {source}; changed lines elided — they are in the diff above)"
            f"\n\n```text\n{body}\n```\n\n"), True


def covered_lines(diff: str, hunks_json: dict | None, path: str) -> tuple[set[int], bool]:
    """New-side lines of `path` that the diff quotes, and whether elision is safe for this file.

    Elision is sound only when the diff really carries every hunk of the file. An edited or truncated
    `package.diff` would delete text from the prompt tier while claiming it is "in the diff above",
    losing the context the tier exists for. So the diff's own parse is checked against `hunks.json`,
    the id source the coverage gate uses: same file, same hunk count. Any disagreement, or a missing
    index, disables elision for that file and it is sent whole.
    """
    in_file = False
    new_no = 0
    lines: set[int] = set()
    hunks_seen = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_file = line.endswith(f" b/{path}")
            continue
        if not in_file:
            continue
        header = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if header:
            new_no = int(header.group(1))
            hunks_seen += 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            lines.add(new_no)
            new_no += 1
        elif line.startswith(" "):
            lines.add(new_no)
            new_no += 1
    if hunks_json is None:
        return lines, False
    expected = next((len(f["hunkIds"]) for f in hunks_json.get("files", []) if f.get("path") == path), 0)
    return lines, expected > 0 and hunks_seen == expected


def build(persona: str, review_dir: pathlib.Path, config: dict, shared: str,
          hunks_json: dict | None) -> tuple[str, dict]:
    """One persona's package, plus a report of what was narrowed and what elided."""
    report: dict = {"whole": []}
    parts = [shared]
    if config.get("size_gate"):
        parts += ["\n---\n\n# Size gate\n\n", config["size_gate"].rstrip() + "\n"]
    spec_path = review_dir / f"spec.{persona}.md"
    if spec_path.is_file():
        parts += ["\n---\n\n## Spec\n\n", spec_path.read_text(encoding="utf-8"), "\n"]
    layers_path = review_dir / "layers.json"
    if layers_path.is_file():
        layers = read_json(layers_path, "the layer map").get("layers") or []
        parts += ["\n---\n\n", reading_map(persona, layers), "\n"]
    parts += [
        "\n---\n\n# Diff (package.diff — every non-generated hunk)\n\n```diff\n",
        (review_dir / "package.diff").read_text(encoding="utf-8"),
        "\n```\n",
    ]
    repo = pathlib.Path(config.get("repo") or ".").resolve()
    consumers = config.get("consumers") or []
    if persona in CONSUMER_LENSES and consumers:
        parts += ["\n---\n\n# Consumers of the changed contracts (unchanged files)\n\n"]
        for path, start, end, label in consumers:
            parts.append(excerpt(repo, path, start, end, label))
    prompt_files = config.get("prompt_files") or []
    if persona == "prompt-quality" and prompt_files:
        parts += [
            "\n---\n\n# Prompt tier: complete changed prompt and contract files\n\n",
            "The diff above shows what changed; these are the same files with the changed lines "
            "elided and every unchanged line kept, because a rule collides with the text around it "
            "rather than with itself. Line numbers prefix every kept line, so an anchor resolves "
            "against the file; an elided range is marked with the lines it stands for.\n\n",
        ]
        diff = (review_dir / "package.diff").read_text(encoding="utf-8")
        for path in prompt_files:
            block, elided = full_file(repo, path, diff, hunks_json)
            parts.append(block)
            if not elided:
                report["whole"].append(path)
    return "".join(parts), report


def check_inputs(review_dir: pathlib.Path, config: dict) -> str:
    """A missing prerequisite or a PR-mode leak, as an error message; "" when the run may proceed.

    A PR review reads only the PR head, and both extras come from the local git index, so a PR
    package carrying them would hand a persona checkout code the mode forbids, unlabelled.
    """
    for required in ("package.diff", "hunks.index.md"):
        if not (review_dir / required).is_file():
            return f"{review_dir} has no {required}; run review-hunks.py first"
    if config.get("mode_kind") == "pr":
        leaked = [key for key in ("consumers", "prompt_files") if config.get(key)]
        if leaked:
            return (f"{', '.join(leaked)} read the local git index, which PR mode "
                    "forbids; fetch those excerpts at the PR head and put them in the dispatch prompt")
    return ""


def assemble_all(review_dir: pathlib.Path, config: dict, hunks_json: dict | None) -> list[tuple]:
    """Every package, built before any is written.

    A refusal on persona four must not leave personas one to three written beside four stale ones
    from an earlier run, which is a package set nobody can tell apart from a complete one.
    """
    assembled = []
    for persona in PERSONAS:
        shared, guidance_report = common(review_dir, config, persona)
        content, report = build(persona, review_dir, config, shared, hunks_json)
        assembled.append((persona, content, report, guidance_report))
    return assembled


def write_packages(review_dir: pathlib.Path, assembled: list[tuple]) -> None:
    """Write each package and print its size plus whatever the run narrowed or sent whole."""
    for persona, content, report, guidance_report in assembled:
        (review_dir / f"{persona}.in.md").write_text(content, encoding="utf-8")
        narrowed = sum(len(v) for v in guidance_report["dropped"].values())
        notes = []
        if narrowed:
            # Printed, never silent: a lens given the wrong sections loses a rule silently.
            notes.append(f"guidance narrowed, {narrowed} section(s) dropped: "
                         + "; ".join(f"{p.split('/')[-1]}: {', '.join(v)}"
                                     for p, v in guidance_report["dropped"].items() if v))
        if report["whole"]:
            notes.append("prompt files sent whole (elision unsafe): "
                         + ", ".join(p.split("/")[-1] for p in report["whole"]))
        print(f"{persona:<15} {len(content):>7} bytes"
              + (f"  [{' | '.join(notes)}]" if notes else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compose one reviewer context package per persona from a review run's artifacts.",
        epilog="Per-run judgement comes from assemble.json in the review directory; see the module "
               "docstring for every key.",
    )
    parser.add_argument("review_dir", type=pathlib.Path, help="<task>/review/<timestamp>")
    parser.add_argument("--config", type=pathlib.Path,
                        help="config file, default <review_dir>/assemble.json")
    args = parser.parse_args(argv)
    review_dir = args.review_dir.resolve()
    config = read_config(review_dir, args.config.resolve() if args.config else None)
    problem = check_inputs(review_dir, config)
    if problem:
        print(f"assemble-packages: {problem}", file=sys.stderr)
        return 2
    hunks_path = review_dir / "hunks.json"
    hunks_json = read_json(hunks_path, "the hunk index") if hunks_path.is_file() else None
    try:
        assembled = assemble_all(review_dir, config, hunks_json)
    except ValueError as error:
        print(f"assemble-packages: {error}", file=sys.stderr)
        return 2
    write_packages(review_dir, assembled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
