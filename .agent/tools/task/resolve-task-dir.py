#!/usr/bin/env python3
"""resolve-task-dir.py — resolve TASK_DIR for a repo+branch via .task-id reverse lookup.

PROGRESS.md may contain optional `[ts] METRIC: ...` audit lines; they are never read here.

By default reads remote + branch from the current git context.
Use --remote / --branch to override (e.g. crew-cleanup resolving a different worktree's tasks).
Use --all to return every matching dir (one per line) instead of the single best match.

Outputs the absolute TASK_DIR path to stdout, or empty string if no active task.
Exits 1 if git state is unresolvable (no remote configured, not on a branch).

Usage (hard — abort caller if git state is broken):
  TASK_DIR=$(~/.agent/bin/resolve-task-dir.py) || exit 1

Usage (soft — skip session capture / optional logging):
  TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null || echo "")

Usage (crew-cleanup — all matches for a specific worktree's remote+branch):
  mapfile -t DIRS < <(~/.agent/bin/resolve-task-dir.py \\
    --remote "$WORKTREE_REMOTE" --branch "$WORKTREE_BRANCH" --all 2>/dev/null || true)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

# The shared `## Status` contract is a snake_case module beside this tool, because a hyphenated
# name cannot be imported. `resolve()` follows the installed ~/.agent/bin symlink back into the repo,
# so the sibling directory is correct whether the tool runs from the tree or the flat surface.
for _dir in (Path(__file__).resolve().parent,):
    if (_dir / "task_status.py").is_file() and str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
from task_status import read_status  # noqa: E402  shared `## Status` contract


def git_output(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_spec_status(spec_path: str | Path) -> str | None:
    """Delegate to the shared contract so hooks and tools cannot diverge."""
    return read_status(spec_path)


def resolve_context(args: argparse.Namespace) -> tuple[str, str]:
    """The remote and branch to match on, from the flags or the current git context.

    An unresolvable remote or a detached HEAD is a broken pipeline state, not "no task": the
    caller aborts on exit 1 rather than silently taking the no-task path.
    """
    if args.remote:
        current_remote = args.remote
    else:
        current_remote = git_output(["git", "remote", "get-url", "origin"])
        if not current_remote:
            print("No git remote configured; cannot resolve task state.", file=sys.stderr)
            sys.exit(1)

    if args.branch:
        current_branch = args.branch
    else:
        current_branch = git_output(["git", "branch", "--show-current"])
        if not current_branch:
            print("Not on a branch; crew commands require an active branch.", file=sys.stderr)
            sys.exit(1)
    return current_remote, current_branch


def matching_tasks(current_remote: str, current_branch: str) -> list[tuple[str, str]]:
    """Every `(created_at, task_dir)` whose `.task-id` matches this remote and branch.

    A task is written on one branch and implemented on another, so either recorded branch
    matches; matching only `branch` stranded the drafting checkout after implementation.
    """
    tasks_glob = os.path.expanduser("~/.agent/tasks/*/.task-id")
    matches = []
    for task_id_file in glob.glob(tasks_glob):
        try:
            with open(task_id_file) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            print(f"Warning: malformed .task-id at {task_id_file} — skipping.", file=sys.stderr)
            continue

        task_branches = {data.get("branch", "")}
        if data.get("spec_branch"):
            task_branches.add(data["spec_branch"])
        if data.get("repo_remote_url", "") == current_remote and current_branch in task_branches:
            matches.append((data.get("created_at", ""), str(Path(task_id_file).parent)))
    return matches


def best_match(matches: list[tuple[str, str]]) -> str:
    """The most recent non-DONE task, else the most recent one.

    A spec whose status cannot be read is not ranked as open: an unreadable spec is unknown,
    and silently preferring it over a readable open task is worse than choosing by date.
    """
    if len(matches) == 1:
        return matches[0][1]
    best = None
    best_date = ""
    for created_at, task_dir in matches:
        spec_status = read_spec_status(os.path.join(task_dir, "SPEC.md"))
        if spec_status is not None and spec_status.lower() != "done":
            if best is None or created_at > best_date:
                best = task_dir
                best_date = created_at
    if best is None:
        return sorted(matches, key=lambda entry: entry[0] or "", reverse=True)[0][1]
    return best


def print_matches(args: argparse.Namespace, matches: list[tuple[str, str]],
                  current_remote: str, current_branch: str) -> None:
    """The `--all` output: every match, as JSON when asked and one path per line otherwise."""
    if args.json:
        print(json.dumps({"remote": current_remote, "branch": current_branch, "matches": [
            {"task_dir": task_dir, "created_at": created_at,
             "status": read_spec_status(os.path.join(task_dir, "SPEC.md"))}
            for created_at, task_dir in matches
        ]}))
        return
    for _, task_dir in matches:
        print(task_dir)


def print_resolved(args: argparse.Namespace, best: str, current_remote: str,
                   current_branch: str) -> None:
    """The single-match output, as a structured record when `--json` is asked."""
    if not args.json:
        print(best)
        return
    metadata_path = Path(best) / ".task-id"
    try:
        metadata = json.loads(metadata_path.read_text())
    except (OSError, json.JSONDecodeError):
        metadata = {}
    print(json.dumps({
        "task_dir": best, "remote": current_remote, "branch": current_branch,
        "status": read_spec_status(os.path.join(best, "SPEC.md")),
        "slug": metadata.get("slug"), "created_at": metadata.get("created_at"),
        "has_spec": (Path(best) / "SPEC.md").is_file(),
        "has_report": (Path(best) / "REPORT.md").is_file(),
        "has_review": (Path(best) / "REVIEW.md").is_file(),
    }))


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


def main() -> int:
    args = build_parser().parse_args()
    current_remote, current_branch = resolve_context(args)
    matches = matching_tasks(current_remote, current_branch)

    if not matches:
        if args.json:
            print(json.dumps({"task_dir": None, "remote": current_remote, "branch": current_branch,
                              "status": None, "matches": []}))
        else:
            print("")
        return 0

    if args.all:
        print_matches(args, matches, current_remote, current_branch)
        return 0

    best = best_match(matches)
    if len(matches) > 1:
        print(
            f"Multiple tasks found for this repo+branch. Using: {best} (most recent non-DONE).",
            file=sys.stderr,
        )
    print_resolved(args, best, current_remote, current_branch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
