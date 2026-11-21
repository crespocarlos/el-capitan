#!/usr/bin/env python3
"""Resolving and creating one branch's worktree: where it goes, and what `worktree add` runs.

The create path is separate from the listing and the mutations because it makes a directory and a
branch, and its failure modes are its own: an occupied target is a refusal with a message naming the
branch already there, and a fetch that cannot reach the remote must stop before anything is created.
The suffix form (`<name>-<short sha>`) is for a target directory that exists but belongs to no
worktree, so two checkouts of one branch cannot silently share a path.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lib.git import GitError, current_branch, fetch_remote, head_sha, run_git
from task_worktrees import worktrees


def existing_worktree(branch: str, top: Path) -> str | None:
    """The path of the worktree already holding `branch`, or None when none does."""
    try:
        if current_branch(None) == branch:
            return str(top)
    except GitError:
        pass
    for path, held in worktrees():
        if held == branch:
            return str(path)
    return None


def target_path(branch: str, top: Path) -> tuple[Path | None, int]:
    """Where the new worktree goes, or the exit code that refuses to reuse an occupied path."""
    target = top.parent / "worktrees" / f"{top.name}-{branch.replace('/', '-')}"
    if not target.is_dir():
        return target, 0
    collision = next((held for path, held in worktrees() if path.resolve() == target.resolve()),
                     None)
    if collision:
        print(f"Error: {target} is already a worktree for branch '{collision}'. "
              f"Cannot reuse for '{branch}'.", file=sys.stderr)
        return None, 1
    return target.with_name(f"{target.name}-{head_sha(None, short=True)}"), 0


def add_command(branch: str, base: str | None, target: Path) -> list[str]:
    """The `worktree add` arguments, without the leading `git`."""
    if base:
        return ["worktree", "add", "-b", branch, str(target), base]
    return ["worktree", "add", str(target), f"origin/{branch}"]


def create(branch: str, base: str | None, top: Path) -> tuple[int, str]:
    """Add the worktree, fetching its base first; `(exit code, path or error message)`.

    A base that is not `origin/<branch>` (a SHA, say) is used as given: it names a commit, not a
    remote ref, and asking the remote for it would fail a well-formed create.
    """
    target, code = target_path(branch, top)
    if target is None:
        return code, ""
    if not base or base.startswith("origin/"):
        try:
            fetch_remote(None, "origin", (base or branch).removeprefix("origin/"))
        except GitError as error:
            return 2, str(error)
    target.parent.mkdir(exist_ok=True, parents=True)
    created = run_git(None, add_command(branch, base, target), check=False)
    if created.returncode:
        return created.returncode, created.stderr.strip()
    return 0, str(target.resolve())
