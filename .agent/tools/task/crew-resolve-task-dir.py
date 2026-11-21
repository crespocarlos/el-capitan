#!/usr/bin/env python3
"""crew-resolve-task-dir.py — resolve TASK_DIR for a repo+branch via .task-id reverse lookup.

PROGRESS.md may contain optional `[ts] METRIC: ...` audit lines; they are never read here.

By default reads remote + branch from the current git context.
Use --remote / --branch to override (e.g. crew-cleanup resolving a different worktree's tasks).
Use --all to return every matching dir (one per line) instead of the single best match.

Outputs the absolute TASK_DIR path to stdout, or empty string if no active task.
Exits 1 if git state is unresolvable (no remote configured, not on a branch).

Usage (hard — abort caller if git state is broken):
  TASK_DIR=$(~/.agent/bin/crew-resolve-task-dir.py) || exit 1

Usage (soft — skip session capture / optional logging):
  TASK_DIR=$(~/.agent/bin/crew-resolve-task-dir.py 2>/dev/null || echo "")

Usage (crew-cleanup — all matches for a specific worktree's remote+branch):
  mapfile -t DIRS < <(~/.agent/bin/crew-resolve-task-dir.py \\
    --remote "$WORKTREE_REMOTE" --branch "$WORKTREE_BRANCH" --all 2>/dev/null || true)

The lookup itself lives in `task_state.py`, shared with `crew-task-context.py`, so the two cannot
disagree about which task a repo+branch owns.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TASK_DIR = Path(__file__).resolve().parent
if str(_TASK_DIR) not in sys.path:
    sys.path.insert(0, str(_TASK_DIR))

from task_resolve import (  # noqa: E402
    ResolverUnavailable,
    best_match,
    matching_tasks,
    resolve_context,
    resolved_record,
)
from task_state import read_status  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
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
    args = build_parser().parse_args()
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
