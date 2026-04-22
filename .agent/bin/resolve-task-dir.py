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
import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path


def git_output(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_spec_status(spec_path):
    # Accepts both two-line `## Status\n<value>` and legacy one-line `## Status: <value>`.
    try:
        with open(spec_path) as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "## Status" and i + 1 < len(lines):
                return lines[i + 1].strip()
            if stripped.startswith("## Status:"):
                return stripped[len("## Status:") :].strip()
    except OSError:
        pass
    return ""


def main():
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
    args = parser.parse_args()

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

    tasks_glob = os.path.expanduser("~/.agent/tasks/*/.task-id")
    matches = []

    for task_id_file in glob.glob(tasks_glob):
        try:
            with open(task_id_file) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            print(f"Warning: malformed .task-id at {task_id_file} — skipping.", file=sys.stderr)
            continue

        file_remote = data.get("repo_remote_url", "")
        file_branch = data.get("branch", "")

        if file_remote == current_remote and file_branch == current_branch:
            created_at = data.get("created_at", "")
            task_dir = str(Path(task_id_file).parent)
            matches.append((created_at, task_dir))

    if not matches:
        print("")
        sys.exit(0)

    if args.all:
        for _, task_dir in matches:
            print(task_dir)
        sys.exit(0)

    if len(matches) == 1:
        print(matches[0][1])
        sys.exit(0)

    # Multiple matches: prefer non-DONE, then most recent created_at
    best = None
    best_date = ""
    for created_at, task_dir in matches:
        spec_path = os.path.join(task_dir, "SPEC.md")
        spec_status = read_spec_status(spec_path)
        if spec_status.lower() != "done":
            try:
                date = created_at
            except Exception:
                date = ""
            if best is None or date > best_date:
                best = task_dir
                best_date = date

    if best is None:
        # All are DONE — pick most recent by created_at
        def sort_key(entry):
            return entry[0] or ""

        matches_sorted = sorted(matches, key=sort_key, reverse=True)
        best = matches_sorted[0][1]

    print(
        f"Multiple tasks found for this repo+branch. Using: {best} (most recent non-DONE).",
        file=sys.stderr,
    )
    print(best)


if __name__ == "__main__":
    main()
