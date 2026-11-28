"""The hunk artifacts of a review: `hunks.json`, `hunks.md`, `hunks.index.md` and `package.diff`.

`check_diff` refuses an empty or non-unified diff and one with no hunk; `write_hunks` writes the four files.
`crew-review-hunks.py` and `prepare` both write through here, so the artifacts have one shape. Parsing:
`review_parse`.
"""
from __future__ import annotations

import json
from pathlib import Path

from review_parse import HUNK_HEADER, parse

GENERATED_TASTE = 60


def index_markdown(parsed: dict) -> str:
    """The hunk index alone: ids, files, changed-line ranges, and size flags.

    This is the compact reference a persona package carries alongside the diff. It orientates
    without re-quoting lines the package already holds, so it costs tens of lines instead of a
    second copy of the patch. Each id carries its new-file start line and span, because a persona
    citing an id in a multi-hunk file otherwise has no way to confirm which hunk a finding belongs
    to, and the coverage gate accepts any real id.
    """
    by_id = {hunk["id"]: hunk for hunk in parsed["hunks"]}
    out = [f"# Hunk index ({len(parsed['hunks'])} hunks in {len(parsed['files'])} files)\n"]
    for entry in parsed["files"]:
        flags = [entry["status"] if entry["status"] != "modified" else "",
                 "likely-generated" if entry["generated"] else "",
                 "diff-too-large" if entry.get("suppressed") else ""]
        ids = ", ".join(
            f"{hunk_id} @{by_id[hunk_id]['newStart']}"
            f"(+{by_id[hunk_id]['additions']}/-{by_id[hunk_id]['deletions']})"
            for hunk_id in entry["hunkIds"])
        label = f" [{', '.join(f for f in flags if f)}]" if any(flags) else ""
        out.append(f"- `{entry['path']}`{label}: {ids}")
    return "\n".join(out)


def markdown(parsed: dict) -> str:
    """Hunk index plus bodies, in the shape the layer-mapping pass reads."""
    by_id = {hunk["id"]: hunk for hunk in parsed["hunks"]}
    out = [index_markdown(parsed), "\n# Hunks\n"]
    for entry in parsed["files"]:
        suffix = f" (renamed from {entry['oldPath']})" if entry["status"] == "renamed" else ""
        if entry["status"] not in {"modified", "renamed"}:
            suffix = f" ({entry['status']})"
        out.append(f"\n## FILE {entry['path']}{suffix}\n")
        for hunk_id in entry["hunkIds"]:
            hunk = by_id[hunk_id]
            context = f" {hunk['context']}" if hunk["context"] else ""
            out.append(f"### {hunk_id} — {hunk['header']}{context}")
            if hunk.get("suppressed"):
                note = ", almost certainly generated" if entry["generated"] else ""
                out.append(f"(+{hunk['additions']}/-{hunk['deletions']}: diff too large to include"
                           f"{note}. Read it only if it matters.)")
            elif hunk["lines"]:
                shown = hunk["lines"][:GENERATED_TASTE] if entry["generated"] else hunk["lines"]
                out.append("```diff")
                for line in shown:
                    more = f" …({line['cut'] - len(line['s'])} more chars)" if line.get("cut") else ""
                    out.append(f"{line['t']}{line['s']}{more}")
                out.append("```")
                if len(shown) < len(hunk["lines"]):
                    out.append(f"({len(hunk['lines']) - len(shown)} more lines of a likely generated "
                               "file omitted)")
            out.append("")
    return "\n".join(out)


def package_diff(diff: str, parsed: dict) -> str:
    """The diff a persona package embeds: generated files keep their headers, not their bodies.

    A lockfile or snapshot hunk costs every persona its full size and carries no reviewable
    intent. Each generated file's hunks collapse to one note naming its ids, so the file stays
    citable and the Reading map's "lines omitted" bullet still matches what the persona sees.
    Only a filename match (`byName`) collapses: the content heuristic that also sets `generated`
    fires on any long-lined prompt or JSON file, which is exactly what a review must read.
    """
    by_id = {hunk["id"]: hunk for hunk in parsed["hunks"]}
    out: list[str] = []
    file_index = -1
    skipping = False
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            file_index += 1
            skipping = False
        elif (not skipping and 0 <= file_index < len(parsed["files"])
                and parsed["files"][file_index]["byName"] and HUNK_HEADER.match(line)):
            entry = parsed["files"][file_index]
            added = sum(by_id[i]["additions"] for i in entry["hunkIds"])
            removed = sum(by_id[i]["deletions"] for i in entry["hunkIds"])
            out.append(f"# {entry['path']}: likely generated, +{added}/-{removed} lines omitted "
                       f"({', '.join(entry['hunkIds'])}); read it only if it matters")
            skipping = True
        if not skipping:
            out.append(line)
    return "\n".join(out)


def check_diff(text: str, origin: str) -> dict:
    """The parsed diff, or ValueError naming why there is nothing to map."""
    if not text.strip():
        raise ValueError(f"{origin} is empty; there is no diff to map")
    if "diff --git " not in text and not HUNK_HEADER.search(text.split("\n")[0]):
        raise ValueError(f"{origin} is not a unified diff (no `diff --git` line)")
    parsed = parse(text)
    if not parsed["hunks"]:
        raise ValueError(f"{origin} contains no hunks")
    return parsed


def write_hunks(parsed: dict, out: Path, package: str) -> None:
    """Write the four hunk artifacts to `out`; `package` is the diff personas embed."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "hunks.json").write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    (out / "hunks.md").write_text(markdown(parsed), encoding="utf-8")
    (out / "hunks.index.md").write_text(index_markdown(parsed) + "\n", encoding="utf-8")
    (out / "package.diff").write_text(package, encoding="utf-8")
