"""The worker lock a live builder holds on its tree, the worker-tree rule, and the BLOCKED line.

`<tree>/.crew-worker.lock` holds `task=<id>` and integer `started=<epoch>` (read by the bash guard
`guard/shell.sh` worker-tree rule, stale after its `STALE_SECONDS`), excluded through `.git/info/exclude`. The orchestrator
writes it (`crew-tool.py task-lock write <tree> <id>`), the builder removes it, `read_locks` reads it for `crew ls --json`
and the TUI; another task's live lock refuses both (`worker_tree`). `blocked` appends one BLOCKED line `crew ls` shows.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from crew.core.task.task_progress import append_blocked, blocked_reason
from crew.lib.clock import utc_stamp
from crew.lib.errors import ToolError
from crew.lib.git import GitError, output

LOCK_NAME = ".crew-worker.lock"
BLOCKED = "BLOCKED: "
LOCK_STALE_SECONDS = 21600  # `STALE_SECONDS` of .claude/hooks/guard/shell.sh: an older lock does not guard


@dataclass(frozen=True)
class Lock:
    """A `.crew-worker.lock`: the tree it guards, its task, and its start (POSIX seconds)."""

    tree: Path
    task: str
    started: float


def parse_lock(tree: Path, text: str) -> Lock | None:
    """The lock `write_lock` wrote, or None when it has no task or no integer start."""
    values = dict(line.partition("=")[::2] for line in text.splitlines() if "=" in line)
    started = values.get("started", "")
    if not values.get("task") or not started.isdigit():
        return None
    return Lock(tree, values["task"], float(started))


def read_locks(trees: list[Path]) -> list[Lock]:
    """The readable locks in `trees`."""
    found = []
    for tree in trees:
        try:
            lock = parse_lock(tree, (tree / LOCK_NAME).read_text(encoding="utf-8"))
        except OSError:
            continue
        found.extend([lock] if lock else [])
    return found


def foreign_lock(tree: Path, own: str) -> Lock | None:
    """The live lock on `tree` when a task other than `own` (or `CREW_WORKER_TASK`) holds it: the worker-tree rule."""
    mine = {own, os.environ.get("CREW_WORKER_TASK", "")} - {""}
    return next((lock for lock in read_locks([tree]) if lock.task not in mine and time.time() - lock.started < LOCK_STALE_SECONDS), None)


def worker_tree(tree: Path, own: str) -> None:
    """Refuse when another task's live worker holds the checkout around `tree`: two stages in one tree would race."""
    try:
        root = Path(output(tree, ["rev-parse", "--show-toplevel"]).strip())
    except (GitError, OSError):
        return  # not a checkout: no worker tree to guard
    lock = foreign_lock(root, own)
    if lock:
        raise ToolError("worker_tree", f"task {lock.task} holds {root} with a live worker", "worker-tree", "wait for that worker, or work in another tree")


def worktree_paths(roots: Iterable[Path | None] = (None,)) -> list[Path]:
    """The worktrees of the repositories around `roots` (None: the cwd), each listed once; none outside a repository."""
    from crew.core.task.task_worktrees import worktrees

    found: dict[Path, None] = {}
    for root in roots:
        try:
            found.update(dict.fromkeys(path for path, _ in ([] if root in found else worktrees(root))))
        except (GitError, OSError):
            continue
    return list(found)


def exclude_path(tree: Path) -> Path:
    """The `info/exclude` file git consults for `tree` (shared by a repository's worktrees)."""
    raw = output(tree, ["rev-parse", "--git-path", "info/exclude"]).strip()
    path = Path(raw)
    return path if path.is_absolute() else tree / path


def write_lock(tree: Path, task: str, now: float | None = None) -> Path:
    """Write the lock and make sure git ignores it; rewriting a lock refreshes its start."""
    worker_tree(tree, task)
    moment = time.time() if now is None else now
    stamp = utc_stamp(moment)
    lock = tree / LOCK_NAME
    lock.write_text(f"task={task}\nstarted={int(moment)}\nstarted_at={stamp}\n", encoding="utf-8")
    try:
        exclude = exclude_path(tree)
        known = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        if LOCK_NAME not in known.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write(("" if not known or known.endswith("\n") else "\n") + LOCK_NAME + "\n")
    except GitError as error:
        print(f"warning: lock not excluded from git ({error})", file=sys.stderr)
    return lock


def remove_lock(tree: Path, task: str = "") -> bool:
    """Delete the lock; True when one was there. Another task's live lock refuses."""
    worker_tree(tree, task)
    lock = tree / LOCK_NAME
    existed = lock.is_file()
    lock.unlink(missing_ok=True)
    return existed


def blocked_lines(tasks: list[tuple[str, Path]]) -> list[str]:
    """`<task>  BLOCKED: <reason>` for each `(name, task dir)` that is blocked, after a blank line."""
    shown = [f"{label}  {BLOCKED}{reason}" for label, directory in tasks if (reason := blocked_reason(directory))]
    return ["", *shown] if shown else []


def blocked(task_dir: Path, reason: str) -> str:
    """Append one BLOCKED line `crew ls` shows; the status does not change."""
    if not task_dir.is_dir():
        raise ToolError("not_a_task", f"blocked: task_dir does not exist: {task_dir}", "block")
    append_blocked(task_dir, reason)
    return ""
