#!/usr/bin/env python3
"""Report what the recorded reviews produced, and how much of it can actually be measured.

Joins each finding under `--tasks-dir` (default `~/.agent/tasks`) to its outcome and prints findings
by label, missing fields and precision per persona (`fixed / (fixed + rejected)`, always with its
denominator and the `unrecorded` count). Usage: crew-review-stats.py [--tasks-dir DIR] [--limit N]
[--max-chars N] [--json]. Exit: 0 the corpus was read, 2 the directory is unusable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import review_bootstrap  # noqa: F401

from review_stats import collect, render

from lib.output import DEFAULT_MAX_CHARS, bounded_json, hint, rows_limit


def default_tasks_dir() -> Path:
    """`~/.agent/tasks`, the place every pipeline run records its review."""
    return Path.home() / ".agent" / "tasks"


def bounded(payload: dict, limit: int | None, max_chars: int) -> dict:
    """Apply `--limit` to the per-review list, then the size ceiling to the whole payload."""
    reviews, marker = rows_limit(payload["reviews"], limit)
    if marker:
        payload = {**payload, "reviews": reviews, "reviewsTotal": len(payload["reviews"]),
                   "truncated": True, "hint": hint("--limit")}
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report review quality: findings by label, missing fields, precision per persona.")
    parser.add_argument("--tasks-dir", type=Path, default=None,
                        help="task store to read (default: ~/.agent/tasks)")
    parser.add_argument("--limit", type=int, default=None,
                        help="show at most N reviews in the review list")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help="bound the printed output; the table and the JSON both honour it")
    parser.add_argument("--json", action="store_true",
                        help="print the whole measurement as JSON on stdout")
    args = parser.parse_args()
    tasks_dir = args.tasks_dir or default_tasks_dir()
    if not tasks_dir.is_dir():
        print(f"review-stats: {tasks_dir} is not a directory; pass --tasks-dir", file=sys.stderr)
        return 2
    payload = bounded(collect(tasks_dir), args.limit, args.max_chars)
    payload = {key: value for key, value in payload.items() if key != "findings"}
    if args.json:
        print(bounded_json(payload, args.max_chars, what="review-stats"))
        return 0
    text = "\n".join(render({**payload, "findings": []}))
    if len(text) > args.max_chars:
        text = text[:args.max_chars] + "\n[truncated: raise --max-chars to see the rest]"
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
