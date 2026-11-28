#!/usr/bin/env python3
"""Split a unified diff into numbered hunks for the reviewer layer map.

Writes `hunks.json`, `hunks.md`, `hunks.index.md` and `package.diff` to `--out`. Hunk ids (`h1`, `h2`,
…) follow diff order, and a file with no textual hunk still gets one, so every changed file has an id
the Reading map and `coverage` share. `package.diff` omits generated files' bodies. Writing: `review_hunks`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from crew.core.review import review_workspace as manifest
from crew.core.review.review_hunks import check_diff, package_diff, write_hunks
from crew.lib.output import DEFAULT_MAX_CHARS, bounded_json


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
    parser = argparse.ArgumentParser(description="Split a unified diff into numbered hunks for the reviewer layer map.")
    parser.add_argument("diff", type=Path, help="unified diff file, or - for stdin")
    parser.add_argument("--out", type=Path, required=True, help="directory for hunks.json, hunks.md, hunks.index.md, and package.diff")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="bound the printed JSON summary")
    parser.add_argument("--since-last-review", action="store_true", help="collapse files whose bytes an earlier round already read (requires --reviewed)")
    parser.add_argument("--reviewed", type=Path, default=None, help="the previous run directory's manifest.json, from `prior-review`")
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
    try:
        parsed = check_diff(text, origin)
    except ValueError as error:
        print(f"review-hunks: {error}", file=sys.stderr)
        return 2
    package, reviewed = reviewed_package(text, parsed, args)
    write_hunks(parsed, args.out, package)
    omitted = [entry["path"] for entry in parsed["files"] if entry["byName"]]
    heuristic = [entry["path"] for entry in parsed["files"] if entry["generated"] and not entry["byName"]]
    summary = {
        "hunks": len(parsed["hunks"]),
        "files": len(parsed["files"]),
        "omitted": omitted,
        "keptDespiteContentFlag": heuristic,
        "alreadyReviewed": reviewed,
        "out": str(args.out),
    }
    print(bounded_json(summary, args.max_chars, what="hunk summary"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
