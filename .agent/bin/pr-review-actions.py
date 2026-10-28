#!/usr/bin/env python3
"""Fetch or plan GitHub PR review-thread actions; mutations require --execute."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def gh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def repository(value: str) -> tuple[str, str]:
    try:
        owner, name = value.split("/", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--repo must be OWNER/REPO") from error
    return owner, name


def fetch(args: argparse.Namespace) -> int:
    query = Path(args.query).expanduser()
    if not query.is_file():
        print(f"query unavailable: {query}", file=sys.stderr)
        return 2
    owner, name = repository(args.repo)
    command = ["api", "graphql", "-F", f"query=@{query}", "-f", f"owner={owner}", "-f", f"repo={name}",
               "-F", f"pr={args.pr}"]
    if args.cursor:
        command.extend(["-f", f"cursor={args.cursor}"])
    result = gh(*command)
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
    }
    if args.command == "reply":
        plan["body"] = args.body
    if not args.execute:
        print(json.dumps({"planned": plan}, indent=2))
        return 0
    owner, name = repository(args.repo)
    if args.command == "resolve":
        result = gh(
            "api", "graphql", "-F", f"threadId={args.thread_id}",
            "-f", "query=mutation($threadId: ID!) { resolveReviewThread(input: {threadId: $threadId}) { thread { isResolved } } }",
        )
    else:
        result = gh(
            "api", f"repos/{owner}/{name}/pulls/{args.pr}/comments/{args.comment_id}/replies",
            "-f", f"body={args.body}",
        )
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    print(result.stdout)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("--repo", required=True)
    fetch_parser.add_argument("--pr", required=True, type=int)
    fetch_parser.add_argument("--cursor")
    fetch_parser.add_argument(
        "--query", default=Path.home() / ".agent/bin/pr-review-threads.graphql", type=Path
    )
    for name in ("resolve", "reply"):
        action = commands.add_parser(name)
        action.add_argument("--repo", required=True)
        action.add_argument("--pr", required=True, type=int)
        action.add_argument("--thread-id", required=True)
        action.add_argument("--execute", action="store_true")
        if name == "reply":
            action.add_argument("--comment-id", required=True)
            action.add_argument("--body", required=True)
    args = parser.parse_args()
    return fetch(args) if args.command == "fetch" else mutation(args)


if __name__ == "__main__":
    sys.exit(main())
