#!/usr/bin/env python3
"""Fetch PR review threads or plan GitHub PR review-thread actions; mutations require --execute.

`reply` and `resolve` print the exact `gh` plan unless `--execute`. The reads (`view`, `diff`, `repo`,
`issue`, with `--field a,b`) and `fetch` (threads as a flat object) replace hand-written `gh` reads;
a missing field prints empty with exit 0, a failed call exits nonzero with gh's stderr. Other
mutations stay literal `gh` in prompts, where the guards see them. Contract: `.agent/tools/TOOLS.md`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import review_bootstrap  # noqa: F401

from review_pr_plan import (
    default_query,
    guard,
    mutation,
    query_command,
    repository,
)
from review_pr_reads import read, threads

from lib.gh_reads import add_read_parser

READS = ("view", "diff", "repo", "issue")


def fetch(args: argparse.Namespace) -> int:
    """The threads as one flat object; a failure prints no JSON, so empty never means failed."""
    query = Path(args.query).expanduser()
    if not query.is_file():
        print(f"query unavailable: {query}", file=sys.stderr)
        return 2
    owner, name = repository(args.repo)
    command = query_command(query, owner, name, args.pr, None)
    if getattr(args, "dry_run", False):
        planned = query_command(query, owner, name, args.pr, args.cursor)
        print(json.dumps({"planned": {"command": planned}}, indent=2))
        return 0
    return threads(command[1:], args.cursor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch", help="review threads as one flat, documented object")
    fetch_parser.add_argument("--repo", required=True)
    fetch_parser.add_argument("--pr", required=True, type=int)
    fetch_parser.add_argument("--cursor", help="resume after this pageInfo.endCursor")
    fetch_parser.add_argument("--query", default=default_query(), type=Path)
    fetch_parser.add_argument("--dry-run", action="store_true",
                              help="print the plan naming the exact gh command; never calls gh")
    for name in READS:
        add_read_parser(commands, name)
    for name in ("resolve", "reply"):
        action = commands.add_parser(name)
        action.add_argument("--repo", required=True)
        action.add_argument("--pr", required=True, type=int)
        action.add_argument("--thread-id", required=True)
        guard(action)
        if name == "reply":
            action.add_argument("--comment-id", required=True)
            action.add_argument("--body", required=True)
    args = parser.parse_args()
    if args.command == "fetch":
        return fetch(args)
    if args.command in READS:
        return read(args.command, args)
    return mutation(args)


if __name__ == "__main__":
    sys.exit(main())
