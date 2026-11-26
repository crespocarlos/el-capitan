#!/usr/bin/env python3
"""crew-resolve-task-dir.py — resolve TASK_DIR for a repo+branch via .task-id reverse lookup.

Remote and branch come from the current checkout unless `--remote`/`--branch` say otherwise; `--all`
prints every match. Prints the absolute TASK_DIR, or nothing when no task matches; exits 1 when git
state is unresolvable. Usage: `TASK_DIR=$(~/.agent/bin/crew-resolve-task-dir.py) || exit 1`. The
lookup is `task_resolve`, shared with `crew-task-context.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_resolve import (
    ResolverUnavailable,
    best_match,
    matching_tasks,
    resolve_context,
    resolved_record,
)
from task_status import read_status


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve TASK_DIR for a repo+branch via .task-id reverse lookup."
    )
    parser.add_argument("--remote", default="", help="Override git remote URL")
    parser.add_argument("--branch", default="", help="Override git branch name")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Return every matching dir (one per line) instead of the single best match",
    )
    parser.add_argument("--json", action="store_true", help="Emit structured task state")
    return parser


def print_matches(matches: list[tuple[str, str]], record: dict, as_json: bool) -> None:
    """The `--all` output: every match, as JSON when asked and one path per line otherwise."""
    if as_json:
        print(json.dumps({"remote": record["remote"], "branch": record["branch"], "matches": [
            {"task_dir": task_dir, "created_at": created_at,
             "status": read_status(Path(task_dir) / "SPEC.md")}
            for created_at, task_dir in matches
        ]}))
        return
    for _, task_dir in matches:
        print(task_dir)


def main() -> int:
    args = make_parser().parse_args()
    try:
        current_remote, current_branch = resolve_context(args.remote, args.branch)
    except ResolverUnavailable as error:
        print(str(error), file=sys.stderr)
        return 1
    matches = matching_tasks(current_remote, current_branch)
    if not matches:
        if args.json:
            print(json.dumps({"task_dir": None, "remote": current_remote,
                              "branch": current_branch, "status": None, "matches": []}))
        else:
            print("")
        return 0
    if args.all:
        print_matches(matches, {"remote": current_remote, "branch": current_branch}, args.json)
        return 0
    best = best_match(matches)
    if len(matches) > 1:
        print(f"Multiple tasks found for this repo+branch. Using: {best} "
              f"(most recent non-DONE).", file=sys.stderr)
    if args.json:
        print(json.dumps(resolved_record(best, current_remote, current_branch)))
    else:
        print(best)
    return 0


if __name__ == "__main__":
    sys.exit(main())
