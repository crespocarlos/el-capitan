#!/usr/bin/env python3
"""Split a unified diff into numbered hunks for the reviewer layer map.

Writes `hunks.json`, `hunks.md`, `hunks.index.md`, and `package.diff` to `--out`. Every hunk gets a
stable id (`h1`, `h2`, …) in diff order, and a file with no textual hunk (binary, pure rename, mode
change) still gets one, so every changed file can be placed in a layer — the ids the persona Reading
map and the `coverage` gate share. `hunks.md` feeds the layer-mapping pass, `hunks.index.md` the
persona package that already holds the diff, and `package.diff` omits generated files' bodies.

Parsing lives in `review_parse.py`; this file is the argparse entry point and the four renderers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REVIEW_DIR = Path(__file__).resolve().parent
_TOOLS_ROOT = _REVIEW_DIR.parent
for _path in (_TOOLS_ROOT, _REVIEW_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from lib.output import DEFAULT_MAX_CHARS, bounded_json  # noqa: E402
from review_parse import HUNK_HEADER, parse  # noqa: E402,F401
import review_manifest as manifest  # noqa: E402

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


def reviewed_package(text: str, parsed: dict, args: argparse.Namespace) -> tuple[str, list[str]]:
    """`package.diff`, collapsed for files an earlier round already read; plus those paths.

    Opt-in and file-granular by design: a hunk unchanged since the last round can still be newly
    wrong because a change elsewhere invalidated it, so the caller decides whether the saved reading
    is worth the lost cross-file context. With no earlier manifest nothing is collapsed and the
    answer is the ordinary package.
    """
    package = package_diff(text, parsed)
    previous = manifest.read(args.reviewed) if args.since_last_review and args.reviewed else None
    if previous is None:
        return package, []
    root = Path.cwd()
    current = manifest.manifest(root, [entry["path"] for entry in parsed["files"]])
    reviewed = sorted(manifest.unchanged_since(root, current, previous))
    stamp = args.reviewed.parent.name
    return manifest.collapse_reviewed(package, parsed, set(reviewed), stamp), reviewed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split a unified diff into numbered hunks for the reviewer layer map.")
    parser.add_argument("diff", type=Path, help="unified diff file, or - for stdin")
    parser.add_argument("--out", type=Path, required=True,
                        help="directory for hunks.json, hunks.md, hunks.index.md, and package.diff")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help="bound the printed JSON summary")
    parser.add_argument("--since-last-review", action="store_true",
                        help="collapse files whose bytes an earlier round already read "
                             "(requires --reviewed)")
    parser.add_argument("--reviewed", type=Path, default=None,
                        help="the previous run directory's manifest.json, from `prior-review`")
    args = parser.parse_args()

    if str(args.diff) == "-":
        text = sys.stdin.read()
        origin = "stdin"
    else:
        try:
            text = args.diff.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            print(f"review-hunks: {error}", file=sys.stderr)
            return 2
        origin = str(args.diff)
    if not text.strip():
        print(f"review-hunks: {origin} is empty; there is no diff to map", file=sys.stderr)
        return 2
    if "diff --git " not in text and not HUNK_HEADER.search(text.split("\n")[0]):
        print(f"review-hunks: {origin} is not a unified diff (no `diff --git` line)", file=sys.stderr)
        return 2

    parsed = parse(text)
    if not parsed["hunks"]:
        print(f"review-hunks: {origin} contains no hunks", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "hunks.json").write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    (args.out / "hunks.md").write_text(markdown(parsed), encoding="utf-8")
    (args.out / "hunks.index.md").write_text(index_markdown(parsed) + "\n", encoding="utf-8")
    package, reviewed = reviewed_package(text, parsed, args)
    (args.out / "package.diff").write_text(package, encoding="utf-8")
    omitted = [entry["path"] for entry in parsed["files"] if entry["byName"]]
    heuristic = [entry["path"] for entry in parsed["files"] if entry["generated"] and not entry["byName"]]
    summary = {"hunks": len(parsed["hunks"]), "files": len(parsed["files"]),
               "omitted": omitted, "keptDespiteContentFlag": heuristic,
               "alreadyReviewed": reviewed, "out": str(args.out)}
    print(bounded_json(summary, args.max_chars, what="hunk summary"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
