#!/usr/bin/env python3
"""The prompt tier: a complete file, with the regions the diff already quotes elided.

Sending both the whole file and its hunks charges the persona twice for the same bytes: 80 KB of a
measured 158 KB prompt tier was already inside `package.diff`. The elision keeps every unchanged
line — the point of the prompt tier is collisions with text the diff never shows — and replaces
each hunk's own lines with one marker. Every kept line carries its file line number, because
collapsing a run shifts the offset of everything after it.

Elision is sound only when the diff really carries every hunk of the file. An edited or truncated
`package.diff` would delete text from the prompt tier while claiming it is "in the diff above",
losing the context the tier exists for, so the diff's own parse is checked against `hunks.json`:
same file, same hunk count. Any disagreement, or a missing index, disables elision for that file
and it is sent whole.
"""
from __future__ import annotations

import re
from pathlib import Path

from lib.git import GitError, blob_at, rev_parse

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def staged_text(repo: Path, path: str) -> str:
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
