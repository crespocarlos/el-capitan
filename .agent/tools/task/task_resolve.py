#!/usr/bin/env python3
"""Task resolution: the repo+branch to `.task-id` reverse lookup, shared by both entry points.

Resolution lives in one module because `crew-resolve-task-dir.py` and `crew-task-context.py` both
need the answer, and a second copy of this lookup is how the two once disagreed. The resolver entry
point adds only argument handling; task context adds only the artifact reader.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

from task_state import read_status


def git_output(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def resolve_context(remote: str = "", branch: str = "") -> tuple[str, str]:
    """The remote and branch to match on, from the overrides or the current git context.

    An unresolvable remote or a detached HEAD is a broken pipeline state, not "no task": the caller
    aborts on exit 1 rather than silently taking the no-task path.
    """
    if remote:
        current_remote = remote
    else:
        current_remote = git_output(["git", "remote", "get-url", "origin"])
        if not current_remote:
            print("No git remote configured; cannot resolve task state.", file=sys.stderr)
            sys.exit(1)
    if branch:
        return current_remote, branch
    current_branch = git_output(["git", "branch", "--show-current"])
    if not current_branch:
        print("Not on a branch; crew commands require an active branch.", file=sys.stderr)
        sys.exit(1)
    return current_remote, current_branch


def matching_tasks(current_remote: str, current_branch: str) -> list[tuple[str, str]]:
    """Every `(created_at, task_dir)` whose `.task-id` matches this remote and branch.

    A task is written on one branch and implemented on another, so either recorded branch matches;
    matching only `branch` stranded the drafting checkout after implementation.
    """
    matches = []
    for task_id_file in glob.glob(os.path.expanduser("~/.agent/tasks/*/.task-id")):
        try:
            with open(task_id_file) as handle:
                data = json.load(handle)
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

    A spec whose status cannot be read is not ranked as open: an unreadable spec is unknown, and
    silently preferring it over a readable open task is worse than choosing by date.
    """
    if len(matches) == 1:
        return matches[0][1]
    best, best_date = None, ""
    for created_at, task_dir in matches:
        spec_status = read_status(os.path.join(task_dir, "SPEC.md"))
        if spec_status is not None and spec_status.lower() != "done":
            if best is None or created_at > best_date:
                best, best_date = task_dir, created_at
    if best is None:
        return sorted(matches, key=lambda entry: entry[0] or "", reverse=True)[0][1]
    return best


def resolved_record(best: str, current_remote: str, current_branch: str) -> dict:
    """The resolver's JSON record for one chosen task directory."""
    try:
        metadata = json.loads((Path(best) / ".task-id").read_text())
    except (OSError, json.JSONDecodeError):
        metadata = {}
    return {
        "task_dir": best, "remote": current_remote, "branch": current_branch,
        "status": read_status(os.path.join(best, "SPEC.md")),
        "slug": metadata.get("slug"), "created_at": metadata.get("created_at"),
        "has_spec": (Path(best) / "SPEC.md").is_file(),
        "has_report": (Path(best) / "REPORT.md").is_file(),
        "has_review": (Path(best) / "REVIEW.md").is_file(),
    }


def resolve_record(remote: str = "", branch: str = "") -> dict:
    """The resolver's JSON record for one repo+branch, with its ambiguity warning on stderr.

    Empty `task_dir` means no task matches, which is exit 0 for the resolver; a warning naming the
    chosen directory means several matched and the newest non-DONE one won.
    """
    current_remote, current_branch = resolve_context(remote, branch)
    matches = matching_tasks(current_remote, current_branch)
    if not matches:
        return {"task_dir": None, "remote": current_remote, "branch": current_branch,
                "status": None, "matches": []}
    best = best_match(matches)
    if len(matches) > 1:
        print(f"Multiple tasks found for this repo+branch. Using: {best} "
              f"(most recent non-DONE).", file=sys.stderr)
    return resolved_record(best, current_remote, current_branch)
