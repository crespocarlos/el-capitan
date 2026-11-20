#!/usr/bin/env python3
"""Fetch or plan GitHub PR review-thread actions; mutations require --execute.

A reply or resolve mutates GitHub, so it plans by default and performs the call only with
`--execute`. `--dry-run` states that default explicitly, and is how a caller that wants a plan
says so without relying on a flag being absent. The plan names the exact `gh` command, so an
operator can read it, edit it, or run it by hand.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from lib.git import gh  # noqa: E402

DEFAULT_QUERY = Path.home() / ".agent/bin/pr-review-threads.graphql"
RESOLVE_QUERY = ("mutation($threadId: ID!) { resolveReviewThread(input: {threadId: $threadId}) "
                 "{ thread { isResolved } } }")


def repository(value: str) -> tuple[str, str]:
    try:
        owner, name = value.split("/", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--repo must be OWNER/REPO") from error
    return owner, name


def plan_command(query: Path, owner: str, name: str, pr: int, cursor: str | None) -> list[str]:
    command = ["gh", "api", "graphql", "-F", f"query=@{query}", "-f", f"owner={owner}",
               "-f", f"repo={name}", "-F", f"pr={pr}"]
    if cursor:
        command.extend(["-f", f"cursor={cursor}"])
    return command


def mutation_command(args: argparse.Namespace) -> list[str]:
    """The exact `gh` argv for this mutation; the plan prints it so it can be run by hand."""
    owner, name = repository(args.repo)
    if args.command == "resolve":
        return ["gh", "api", "graphql", "-F", f"threadId={args.thread_id}",
                "-f", f"query={RESOLVE_QUERY}"]
    return ["gh", "api", f"repos/{owner}/{name}/pulls/{args.pr}/comments/{args.comment_id}/replies",
            "-f", f"body={args.body}"]


def fetch(args: argparse.Namespace) -> int:
    query = Path(args.query).expanduser()
    if not query.is_file():
        print(f"query unavailable: {query}", file=sys.stderr)
        return 2
    owner, name = repository(args.repo)
    if getattr(args, "dry_run", False):
        print(json.dumps({"planned": {"command": plan_command(query, owner, name, args.pr, args.cursor)}},
                         indent=2))
        return 0
    command = plan_command(query, owner, name, args.pr, args.cursor)
    result = gh(*command[1:])
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    print(result.stdout)
    return 0


def mutation(args: argparse.Namespace) -> int:
    plan = {
        "action": args.command, "repo": args.repo, "pr": args.pr,
        "thread_id": args.thread_id, "comment_id": getattr(args, "comment_id", None),
        "execute": args.execute,
        "command": mutation_command(args),
    }
    if args.command == "reply":
        plan["body"] = args.body
    if not args.execute:
        print(json.dumps({"planned": plan}, indent=2))
        return 0
    result = gh(*plan["command"][1:])
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    print(result.stdout)
    return 0


def guard(action: argparse.ArgumentParser) -> None:
    """`--execute` is the only mutation switch; `--dry-run` is its inverse and forces the plan."""
    mode = action.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true",
                      help="perform the GitHub call (without it, print the plan and exit 0)")
    mode.add_argument("--dry-run", action="store_true",
                      help="print the plan naming the exact gh command; never calls gh")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("--repo", required=True)
    fetch_parser.add_argument("--pr", required=True, type=int)
    fetch_parser.add_argument("--cursor")
    fetch_parser.add_argument("--query", default=DEFAULT_QUERY, type=Path)
    fetch_parser.add_argument("--dry-run", action="store_true",
                              help="print the plan naming the exact gh command; never calls gh")
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
    return fetch(args) if args.command == "fetch" else mutation(args)


if __name__ == "__main__":
    sys.exit(main())
