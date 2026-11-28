#!/usr/bin/env python3
"""Task resolution: the repo+branch to `.task-id` reverse lookup, the one answer `task-context` and the usage
hook share."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from crew.core.task.task_status import read_status
from crew.lib.git import GitError, current_branch, remote_url


class ResolverUnavailable(RuntimeError):
    """Git state that cannot resolve a task: the caller exits 1 rather than reporting "no task"."""


def resolve_context(remote: str = "", branch: str = "") -> tuple[str, str]:
    """The remote and branch to match on, from the overrides or the current git context.

    An unresolvable remote or a detached HEAD is a broken pipeline state, not "no task": git
    answering failure raises here, and the entry point exits 1 instead of silently taking the
    no-task path: empty output is never read as an answer.
    """
    try:
        current_remote = remote or remote_url(None, "origin")
        if not current_remote:
            raise ResolverUnavailable("No git remote configured; cannot resolve task state.")
        if branch:
            return current_remote, branch
        return current_remote, current_branch(None)
    except GitError as error:
        raise ResolverUnavailable(f"Cannot resolve repo and branch from git: {error}") from error


def matching_tasks(current_remote: str, current_branch: str) -> list[tuple[str, str]]:
    """Every `(created_at, task_dir)` whose `.task-id` matches this remote and branch.

    A task is written on one branch and implemented on another, so either recorded branch matches;
    matching only `branch` stranded the drafting checkout after implementation.
    """
    matches = []
    for task_id_file in sorted((Path.home() / ".agent" / "tasks").glob("*/.task-id")):
        try:
            data = json.loads(task_id_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"Warning: malformed .task-id at {task_id_file} — skipping.", file=sys.stderr)
            continue
        task_branches = {data.get("branch", "")}
        if data.get("spec_branch"):
            task_branches.add(data["spec_branch"])
        if data.get("repo_remote_url", "") == current_remote and current_branch in task_branches:
            matches.append((data.get("created_at", ""), str(task_id_file.parent)))
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
        spec_status = read_status(Path(task_dir) / "SPEC.md")
        if spec_status is not None and spec_status.lower() != "done":
            if best is None or created_at > best_date:
                best, best_date = task_dir, created_at
    if best is None:
        return sorted(matches, key=lambda entry: entry[0] or "", reverse=True)[0][1]
    return best


def resolved_record(best: str, current_remote: str, current_branch: str) -> dict:
    """The resolver's JSON record for one chosen task directory."""
    task = Path(best)
    try:
        metadata = json.loads((task / ".task-id").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    return {
        "task_dir": best,
        "remote": current_remote,
        "branch": current_branch,
        "status": read_status(task / "SPEC.md"),
        "slug": metadata.get("slug"),
        "created_at": metadata.get("created_at"),
        "has_spec": (task / "SPEC.md").is_file(),
        "has_report": (task / "REPORT.md").is_file(),
        "has_review": (task / "REVIEW.md").is_file(),
    }


def resolve_record(remote: str = "", branch: str = "") -> dict:
    """The resolver's JSON record for one repo+branch, with its ambiguity warning on stderr.

    Empty `task_dir` means no task matches, which is exit 0 for the resolver; a warning naming the
    chosen directory means several matched and the newest non-DONE one won.
    """
    current_remote, current_branch = resolve_context(remote, branch)
    matches = matching_tasks(current_remote, current_branch)
    if not matches:
        return {"task_dir": None, "remote": current_remote, "branch": current_branch, "status": None, "matches": []}
    best = best_match(matches)
    if len(matches) > 1:
        print(f"Multiple tasks found for this repo+branch. Using: {best} (most recent non-DONE).", file=sys.stderr)
    return resolved_record(best, current_remote, current_branch)
