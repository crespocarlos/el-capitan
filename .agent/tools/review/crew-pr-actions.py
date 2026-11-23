#!/usr/bin/env python3
"""Fetch PR review threads or plan GitHub PR review-thread actions; mutations require --execute.

A reply or resolve mutates GitHub, so it plans by default and performs the call only with
`--execute`. The plan names the exact `gh` command, so an operator can read it, edit it, or run it by
hand. The reads — `view`, `diff`, `repo`, `issue` — exist so a prompt never spells out a `gh` read
plus its `--jq`: `--field a,b` prints one bare line per field in the order asked. `fetch` prints
review threads as a flat object rather than gh's raw GraphQL envelope. A field gh did not return
prints empty with exit 0; a failed call exits nonzero carrying gh's own stderr.

Mutations stay literal `gh` in the prompts — `gh pr create`, `gh pr comment`, `gh issue create` —
because a wrapper would hide the argv from the guard that inspects it. The full contract lives in
`.agent/tools/TOOLS.md` under this command.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
_REVIEW_DIR = Path(__file__).resolve().parent
for _path in (_TOOLS_ROOT, _REVIEW_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from review_pr_plan import (  # noqa: E402
    default_query,
    guard,
    mutation,
    query_command,
    repository,
)
from review_pr_reads import add_read_parser, read, threads  # noqa: E402

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
