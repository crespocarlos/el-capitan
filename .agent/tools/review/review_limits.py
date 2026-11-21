#!/usr/bin/env python3
"""Size policy for a parsed diff: which files are generated, and which are too large to quote.

A lockfile, a snapshot, or a minified bundle costs every persona its full size and carries no
reviewable intent, so it is detected and its bodies are dropped while its hunk ids survive. The
same applies to a hunk larger than `SUPPRESS_LINES` or `SUPPRESS_CHARS`: the ids stay addressable so
the layer map still covers the file, and only the text goes.

Two signals set `generated`, and they are not interchangeable. `byName` is a filename match, and it
is the only one that lets a package collapse the file's body: the content heuristic fires on any
long-lined prompt or JSON file, which is exactly what a review must read.
"""
from __future__ import annotations

import re

GENERATED = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.sum|Cargo\.lock|poetry\.lock|uv\.lock"
    r"|Gemfile\.lock|composer\.lock)$|__snapshots__/|\.snap$|(^|/)dist/|\.min\.(js|css)$|\.map$"
    r"|\.gen\.|_generated|\.generated\.|(^|/)generated/|(^|/)__generated__/|\.pb\.go$"
    r"|_pb2(_grpc)?\.py$|(^|/)vendor/|\.bundled\.(json|ya?ml)$"
)
SUPPRESS_LINES = 5000
SUPPRESS_CHARS = 500_000
LARGE_LINES = 400
MAX_LINE_CHARS = 5000


def new_file(path: str, old_path: str) -> dict:
    """A file record before its hunks are seen; `byName` is what a package may collapse."""
    return {"path": path, "oldPath": old_path, "status": "modified",
            "generated": bool(GENERATED.search(path)), "byName": bool(GENERATED.search(path)),
            "hunkIds": []}


def apply_limits(files: list[dict], hunks: list[dict]) -> None:
    """Flag oversized and generated-by-content files, and cut a line that would dwarf the package."""
    by_file: dict[str, list[dict]] = {}
    for hunk in hunks:
        by_file.setdefault(hunk["file"], []).append(hunk)
    for entry in files:
        owned = by_file.get(entry["path"], [])
        total = sum(h["additions"] + h["deletions"] for h in owned)
        chars = sum(len(line["s"]) for h in owned for line in h["lines"])
        longest = max((len(line["s"]) for h in owned for line in h["lines"]), default=0)
        # Minified or machine-written content counts as generated even with a plain name.
        if longest > 2000 or (chars and chars / max(total, 1) > 400):
            entry["generated"] = True
        if total > SUPPRESS_LINES or chars > SUPPRESS_CHARS:
            entry["suppressed"] = True
            entry["size"] = chars
            for h in owned:
                h["suppressed"] = True
                h["lines"] = []
            continue
        if total > LARGE_LINES:
            entry["large"] = True
        for h in owned:
            for line in h["lines"]:
                if len(line["s"]) > MAX_LINE_CHARS:
                    line["cut"] = len(line["s"])
                    line["s"] = line["s"][:MAX_LINE_CHARS]
