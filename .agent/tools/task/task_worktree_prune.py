#!/usr/bin/env python3
"""Pruning stale worktree registrations, and the fetch interval that keeps the check cheap.

A registration whose directory is gone, or whose branch no longer exists, is a stale entry every
later listing has to skip. Pruning it is safe; removing a worktree whose branch is gone and unmerged
is not, so that branch survives and the decision is presented by `crew cleanup` instead.

The fetch is skipped inside the hour because `crew-worktree.py` resolves on every implementation
start, and a network round trip there would be paid by a machine that already knows the answer.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from lib.git import GitError, output, run_git
from task_worktrees import listing, remove


def fetch_if_stale(git_dir: Path, dry_run: bool) -> None:
    """Fetch when the last one is older than an hour, so a resolve costs no round trip."""
    fetch_head = git_dir / "FETCH_HEAD"
    if fetch_head.exists() and time.time() - fetch_head.stat().st_mtime < 3600:
        return
    if dry_run:
        print("dry-run: git fetch --prune --quiet", file=sys.stderr)
        return
    run_git(None, ["fetch", "--prune", "--quiet"], check=False)


def prune_stale(dry_run: bool) -> None:
    """Prune stale registrations, then remove the worktrees whose remote branch is gone.

    A gone branch that was never merged keeps its local branch: its commits exist nowhere else, so
    deleting it would discard work nobody agreed to lose.
    """
    if dry_run:
        print("dry-run: git worktree prune", file=sys.stderr)
    else:
        run_git(None, ["worktree", "prune"], check=False)
    try:
        git_dir = Path(output(None, ["rev-parse", "--git-dir"]))
        entries = listing()
    except GitError as error:
        print(f"manage-worktree: cannot inspect this checkout: {error}", file=sys.stderr)
        return
    fetch_if_stale(git_dir, dry_run)
    for entry in entries:
        if not entry["gone"] or entry["main"]:
            continue
        if dry_run:
            print(f"dry-run: prune stale worktree {entry['path']} ({entry['branch']})",
                  file=sys.stderr)
            continue
        code, message = remove(Path(entry["path"]),
                               entry["branch"] if entry["merged"] else None)
        if code:
            print(f"manage-worktree: {message}", file=sys.stderr)
            continue
        print(f"Pruned stale worktree: {entry['path']} ({entry['branch']})", file=sys.stderr)
        if not entry["merged"]:
            print(f"Kept local branch {entry['branch']} (remote gone, not merged). "
                  "Run `crew cleanup` to review it.", file=sys.stderr)
        elif "branch " in message:
            print(f"Deleted local branch: {entry['branch']}", file=sys.stderr)
