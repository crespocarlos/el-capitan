#!/usr/bin/env python3
"""Building the reviewer packages and writing them: the diff, the per-persona tail, the prompt tier,
the optional slice, and the size and skip record merged into `manifest.json`.

Order is the cost model: the shared header and the whole diff come first, byte-identical for every
persona, so a cached prefix is paid once per run. Every package is built before any is written.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import review_bootstrap  # noqa: F401

from assemble_inputs import (
    CONSUMER_LENSES,
    PERSONAS,
    PRIMARY_KINDS,
    changed_paths,
    common,
    decide,
    guidance_block,
    prior_section,
    read_artifact,
    reading_map,
)
from review_workspace import MANIFEST_FILE
from task_verify_report import capped

from lib.git import GitError, blob_at, rev_parse

DIFF_HEADING = "\n---\n\n# Diff (package.diff — every non-generated hunk)\n\n```diff\n"
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
SLICED = ("product-flow", "code-quality")
DEFINES = re.compile(r"\b(?:def|class|function|const|let|var|interface|type|enum|fn|func|struct|trait)"
                     r"\s+([A-Za-z_]\w{3,})")
MIN_NAME = 4
SCHEMA_VERSION = 1  # of the `personas` record in manifest.json


def unverified_block(report: str | None) -> str:
    """The builder's unverified claims from REPORT.md (config key `report`); '' when absent or unreadable."""
    try:
        text = Path(report).read_text(encoding="utf-8") if report else ""
    except OSError:
        return ""
    lines = capped(text, 20)
    return "\n".join(lines) + "\n" if lines else ""


def tail(persona: str, review_dir: Path, config: dict) -> tuple[list[str], dict]:
    """The per-persona material that follows the diff: everything a lens reads alone."""
    parts: list[str] = []
    report: dict = {"whole": [], "guidance": {}}
    if config.get("size_gate"):
        parts += ["\n---\n\n# Size gate\n\n", config["size_gate"].rstrip() + "\n"]
    claims = unverified_block(config.get("report"))
    if claims:
        parts += ["\n---\n\n## Builder's unverified claims (from REPORT.md)\n\n", claims]
    spec_path = review_dir / f"spec.{persona}.md"
    if spec_path.is_file():
        parts += ["\n---\n\n## Spec\n\n", spec_path.read_text(encoding="utf-8"), "\n"]
    layers_path = review_dir / "layers.json"
    if layers_path.is_file():
        layers = read_artifact(layers_path, "the layer map").get("layers") or []
        parts += ["\n---\n\n", reading_map(persona, layers), "\n"]
    guidance, guidance_report = guidance_block(review_dir, persona, config)
    if guidance:
        parts += ["\n---\n\n# Repository guidance\n\n", guidance]
    report["guidance"] = guidance_report
    prior = config.get("prior_review_dir")
    if prior:
        block = prior_section(Path(prior))
        if block:
            parts += ["\n---\n\n", block]
    return parts, report


def extras(persona: str, config: dict, diff: str,
           hunks_json: dict | None, report: dict) -> list[str]:
    """The consumer excerpts and prompt tier, which read the repository rather than the run."""
    parts: list[str] = []
    repo = Path(config.get("repo") or ".").resolve()
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
        for path in prompt_files:
            block, elided = full_file(repo, path, diff, hunks_json)
            parts.append(block)
            if not elided:
                report["whole"].append(path)
    return parts


def build(persona: str, review_dir: Path, config: dict, shared: str,
          hunks_json: dict | None, sliced: dict | None = None) -> tuple[str, dict]:
    """One persona's package and what was narrowed or elided; `sliced` narrows this lens's diff.

    The diff is read once, so the prompt tier decides elision on the same bytes the package quotes.
    """
    diff = (review_dir / "package.diff").read_text(encoding="utf-8")
    shown = diff if sliced is None else sliced["text"]
    heading = DIFF_HEADING if sliced is None else DIFF_HEADING.replace(
        "every non-generated hunk", f"sliced to {sliced['files']} of {sliced['of']} files for this lens; "
        "the rest are with the lenses that read the whole diff")
    parts = [shared, heading, shown, "\n```\n"]
    tail_parts, report = tail(persona, review_dir, config)
    parts += tail_parts
    parts += extras(persona, config, diff, hunks_json, report)
    return "".join(parts), report


def assemble_all(review_dir: Path, config: dict, hunks_json: dict | None) -> list[tuple]:
    """Every package, built before any is written; the shared head is built once, so it is identical."""
    head = common(review_dir, config)
    assembled = []
    for persona in PERSONAS:
        content, report = build(persona, review_dir, config, head, hunks_json)
        assembled.append((persona, content, report))
    return assembled


def write_packages(review_dir: Path, assembled: list[tuple]) -> None:
    """Write each package and print its size plus whatever the run narrowed or sent whole."""
    for persona, content, report in assembled:
        (review_dir / f"{persona}.in.md").write_text(content, encoding="utf-8")
        guidance_report = report["guidance"]
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


def staged_text(repo: Path, path: str) -> str:
    """The staged content of a tracked file (what a staged review judges), else the working tree.

    Outside a repository or for an untracked file the working tree is the source, and the label says so.
    """
    try:
        return blob_at(repo, f":{path}")
    except GitError:
        return (repo / path).read_text(encoding="utf-8")


def is_staged(repo: Path, path: str) -> bool:
    """True when `path` has an index entry; the index is the only place `blob_at` reads."""
    try:
        rev_parse(repo, f":{path}")
    except GitError:
        return False
    return True


def excerpt(repo: Path, path: str, start: int, end: int, label: str) -> str:
    """A numbered slice of a file, for the consumer excerpts a code lens receives."""
    lines = staged_text(repo, path).splitlines()[start - 1:end]
    body = "\n".join(f"{start + index}: {line}" for index, line in enumerate(lines))
    language = Path(path).suffix.lstrip(".") or "text"
    return f"### `{path}:{start}-{end}` ({label})\n\n```{language}\n{body}\n```\n\n"


def covered_lines(diff: str, hunks_json: dict | None, path: str) -> tuple[set[int], bool]:
    """New-side lines of `path` that the diff quotes, and whether elision is safe for this file."""
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
        header = HUNK_HEADER.match(line)
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


def full_file(repo: Path, path: str, diff: str, hunks_json: dict | None) -> tuple[str, bool]:
    """A complete file, eliding the lines the diff already carries when that is provably safe."""
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


def split_diff(diff: str) -> dict[str, str]:
    """`{path: that file's diff text}` in diff order."""
    blocks = re.split(r"(?m)^(?=diff --git )", diff)
    blocks = [b for b in blocks if b.startswith("diff --git ")]
    return dict(zip(changed_paths(diff), blocks))


def names_defined(path: str, text: str) -> set[str]:
    """Symbols a file's changed lines define, plus its module stem."""
    changed = "\n".join(line[1:] for line in text.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---"))
    found = set(DEFINES.findall(changed))
    stem = Path(path).stem
    if len(stem) >= MIN_NAME:
        found.add(stem)
    return found


def mentions(text: str, names: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", text) for name in names)


def closure(seed: set[str], files: dict[str, str]) -> set[str]:
    """`seed` plus every file linked to it by a changed name, to a fixpoint."""
    chosen = set(seed)
    defined = {path: names_defined(path, text) for path, text in files.items()}
    grown = True
    while grown:
        grown = False
        for path, text in files.items():
            if path in chosen:
                continue
            callers = any(mentions(text, defined[s]) for s in chosen)
            callees = mentions("\n".join(files[s] for s in chosen), defined[path])
            if callers or callees:
                chosen.add(path)
                grown = True
    return chosen


def seed_files(persona: str, layers: list[dict], hunk_file: dict[str, str]) -> set[str]:
    kinds = PRIMARY_KINDS[persona]
    return {hunk_file[h] for layer in layers if layer.get("kind") in kinds
            for h in layer.get("hunks") or [] if h in hunk_file}


def plan(layers: list[dict], hunks_json: dict | None, diff: str, packaged: list[str]) -> tuple[dict[str, dict], str]:
    """`({persona: {files, of, closure, paths}}, note)`; empty plan with a note when nothing is sliced."""
    files = split_diff(diff)
    hunks = (hunks_json or {}).get("hunks") or []
    if not layers or not hunks or not files:
        return {}, "slicing needs a layer map and a hunk index; every lens gets the whole diff"
    hunk_file = {h["id"]: h["file"] for h in hunks if isinstance(h, dict) and "id" in h and "file" in h}
    sliced: dict[str, dict] = {}
    for persona in SLICED:
        if persona not in packaged:
            continue
        seed = seed_files(persona, layers, hunk_file) & set(files)
        chosen = closure(seed, files) if seed else set()
        if not chosen or chosen >= set(files):
            continue
        sliced[persona] = {"files": len(chosen), "of": len(files), "closure": sorted(chosen - seed),
                           "paths": [p for p in files if p in chosen]}
    full = [p for p in packaged if p not in sliced]
    covered = set(hunk_file) if full else {h for n in sliced.values() for h, f in hunk_file.items() if f in n["paths"]}
    if covered != set(hunk_file):
        return {}, "coverage gate: a hunk would reach no persona; every lens gets the whole diff"
    return sliced, ""


def slice_text(diff: str, paths: list[str]) -> str:
    """The diff restricted to `paths`, in diff order."""
    files = split_diff(diff)
    return "".join(files[p] for p in files if p in set(paths))


def layers_of(review_dir: Path) -> list[dict]:
    path = review_dir / "layers.json"
    return (read_artifact(path, "the layer map").get("layers") or []) if path.is_file() else []


def assemble_run(review_dir: Path, config: dict, hunks_json: dict | None) -> tuple[list[tuple], dict, dict, str]:
    """`(assembled, skipped, sliced, note)`; nothing is written."""
    diff = (review_dir / "package.diff").read_text(encoding="utf-8")
    packaged, skipped = decide(PERSONAS, diff, config)
    sliced, note = ({}, "")
    if config.get("slice") is True:
        sliced, note = plan(layers_of(review_dir), hunks_json, diff, packaged)
    head = common(review_dir, config)
    assembled = []
    for persona in packaged:
        cut = None
        if persona in sliced:
            cut = {**sliced[persona], "text": slice_text(diff, sliced[persona]["paths"])}
        content, report = build(persona, review_dir, config, head, hunks_json, cut)
        assembled.append((persona, content, report))
    return assembled, skipped, sliced, note


def write_run(review_dir: Path, assembled: list[tuple], skipped: dict, sliced: dict, note: str) -> None:
    write_packages(review_dir, assembled)
    sizes = {persona: len(content) for persona, content, _ in assembled}
    for line in size_report(sizes, max(sizes.values(), default=0), skipped, sliced):
        print(line)
    if note:
        print(f"slice: {note}")
    record(review_dir, sizes, skipped, sliced)


def size_report(sizes: dict[str, int], full: int, skipped: dict[str, str], sliced: dict[str, dict]) -> list[str]:
    """The lines printed after the packages: bytes per persona against the full-diff package size."""
    lines = []
    for persona, size in sizes.items():
        share = f"{round(100 * size / full)}% of the largest" if full else "n/a"
        note = sliced.get(persona)
        lines.append(f"size: {persona:<15} {size:>7} bytes ({share})"
                     + (f"; sliced {note['files']} of {note['of']} files, +{len(note['closure'])} by closure"
                        if note else ""))
    lines += [f"skipped: {persona}: {reason}" for persona, reason in skipped.items()]
    return lines


def record(review_dir: Path, sizes: dict[str, int], skipped: dict[str, str], sliced: dict[str, dict]) -> Path:
    """Merge the decisions and sizes into `manifest.json`, keeping whatever the manifest already holds."""
    target = review_dir / MANIFEST_FILE
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["personas"] = {
        "schema_version": SCHEMA_VERSION, "packaged": sorted(sizes), "bytes": sizes,
        "skipped": [{"persona": p, "reason": r} for p, r in sorted(skipped.items())],
        "sliced": {p: {"files": n["files"], "of": n["of"], "closure": n["closure"]} for p, n in sliced.items()},
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
