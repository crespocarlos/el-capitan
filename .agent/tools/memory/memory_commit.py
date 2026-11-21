#!/usr/bin/env python3
"""Committing the memory store: the lock, the conflict check, and the rollback.

Every mutation reaches git from here rather than from the module that changed a file, so there is
one place that refuses to commit across a merge conflict and one place that restores a failed
write. A `git add -A` on a conflicted file marks the working tree — conflict markers included — as
the resolution, so the check runs before any staging: adopting markers silently is the failure this
guards.

`mutate` is the whole protocol: take the lock, commit anything already dirty, apply the caller's
change, reindex, stage, commit, and restore every file the change touched when any step fails.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Callable

from lib.files import atomic_write
from lib.git import GitError, conflicted_paths, dirty_files as _dirty_files, run_git as _run_git
from memory_index import ensure_store, refresh, store_lock, write_indexes_for_scopes
from memory_paths import MemoryError, memory_root


def run_git(arguments: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Git against the memory store, whose repository is not the caller's working directory."""
    return _run_git(memory_root(), list(arguments), check=check)


def dirty_files() -> list[str]:
    """Paths changed in the memory store, including untracked ones."""
    return _dirty_files(memory_root())


def unresolved_conflicts() -> list[str]:
    """Return conflicted paths, or raise when git cannot answer.

    A failed `git diff` (broken index, missing repo, held lock) is not "no conflicts": reporting
    clean would let `commit_external_changes` adopt conflict markers as the resolution.
    """
    try:
        return conflicted_paths(memory_root())
    except GitError as error:
        raise MemoryError("cannot verify the memory store's merge state: " + str(error)) from error


def git_commit(message: str) -> None:
    result = run_git([
        "-c", "user.name=mem", "-c", "user.email=mem@localhost",
        "commit", "-m", message
    ], check=False)
    if result.returncode:
        raise MemoryError(f"git commit failed: {result.stderr.strip() or result.stdout.strip()}")


def commit_external_changes() -> None:
    """Adopt changes already in the store as one commit, refusing across a merge conflict."""
    conflicts = unresolved_conflicts()
    if conflicts:
        raise MemoryError(
            "memory store has unresolved merge conflicts: " + ", ".join(conflicts)
            + " — resolve them in " + str(memory_root()) + " and retry"
        )
    changes = dirty_files()
    if changes:
        run_git(["add", "-A"])
        git_commit(f"mem: external {len(changes)} files")


def restore_units(backups: list[tuple[Path, str | None]]) -> None:
    """Put every written unit back the way it was, deleting the ones that did not exist."""
    for path, previous in backups:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, previous)


def mutate(operation: str, change: Callable[[], list[tuple[Path, str | None]]]) -> int:
    """Lock, preserve changed unit files, index, commit, and restore on failure."""
    ensure_store()
    with store_lock():
        try:
            commit_external_changes()
            backups = change()
            conn = refresh(write_indexes=False)
            backups.extend(write_indexes_for_scopes(conn))
            conn.close()
            run_git(["add", "-A"])
            if run_git(["diff", "--cached", "--quiet"], check=False).returncode:
                git_commit(operation)
            return 0
        except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryError) as error:
            restore_units(locals().get("backups", []))
            print(str(error), file=sys.stderr)
            return 2
