#!/usr/bin/env python3
"""The `comments` and `check-map` subcommands: drafting bodies, and parsing a layers reply.

Both turn a step that was prose-only into one a prompt cannot skip silently. `comments` writes the
paste-ready file a PR reviewer used to assemble by hand. `check-map` parses a `reviewer-layers` reply
before anything packages it, so a malformed block costs one re-dispatch instead of surfacing at the
coverage gate after every persona has run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.output import bounded_json
from review_comments import comment_body, findings_from, missing_comments, write
from review_map import parse_map_block


def comments(args: argparse.Namespace) -> int:
    """Write `comments.md` and report what it holds; exit 1 when a body is still missing.

    A clean review is not a failure: it writes a file saying so and exits 0, because the report links
    this path and a missing file would read as a broken run.
    """
    review_dir = args.review_dir.resolve()
    findings = findings_from(args.findings or review_dir / "consolidation.json")
    pending = missing_comments(findings, "pr")
    if pending:
        for title in pending:
            print(f"review-findings: no comment drafted for {title!r}", file=sys.stderr)
        return 1
    path = write(review_dir, findings, args.head)
    drafted = [f for f in findings if f.is_emitted() and comment_body(f)]
    print(bounded_json({"comments": str(path), "drafted": len(drafted)}, args.max_chars,
                       what="comments summary"))
    return 0


def check_map(args: argparse.Namespace) -> int:
    """Parse the layers reply and print the map as JSON, or fail naming the parse error."""
    payload = parse_map_block(Path(args.reply).read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    summary = {"layers": len(payload["layers"])}
    if args.output:
        summary["out"] = str(args.output)
    print(bounded_json(summary, args.max_chars, what="layer map"))
    return 0
