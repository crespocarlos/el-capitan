"""The mutation half of `crew-pr-actions.py`: the plan, and the guards around executing it.

`reply` and `resolve` mutate GitHub, so they plan by default and act only on `--execute`. The plan
names the exact `gh` argv, which is what lets an operator read it, edit it, or run it by hand — and
what keeps a mutation out of a wrapper whose argv a caller cannot see. `--dry-run` states the
default explicitly, so a caller that wants a plan says so instead of relying on a flag being absent.
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


def default_query() -> Path:
    """The graphql asset: the installed link when one exists, else the copy beside this file.

    An asset is read, not installed, so `~/.agent/bin` no longer receives a link for it. The
    installed path is still preferred when present, because a plan printed for an operator to run
    by hand should name the stable path they will find.
    """
    if DEFAULT_QUERY.is_file():
        return DEFAULT_QUERY
    return _TOOLS_ROOT / "review" / "pr-review-threads.graphql"


def repository(value: str) -> tuple[str, str]:
    try:
        owner, name = value.split("/", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--repo must be OWNER/REPO") from error
    return owner, name


def query_command(query: Path, owner: str, name: str, pr: int, cursor: str | None) -> list[str]:
    """The argv for one page of review threads; the cursor is added only when a caller passed one."""
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


def mutation(args: argparse.Namespace) -> int:
    """Print the plan, or with `--execute` run exactly the command the plan would have printed."""
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
