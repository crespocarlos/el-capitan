"""`crew-task.py lock`: the worker lock a live builder holds on its tree, and the BLOCKED line.

`<tree>/.crew-worker.lock` holds `task=<id>` and integer `started=<epoch>` (read by the bash guard
`worker-tree.sh`; stale after `STALE_SECONDS`), excluded through `.git/info/exclude`. The orchestrator
writes it (`lock write <tree> --task <id>`), the builder removes it (`lock remove <tree>`).
`blocked <TASK_DIR> "<reason>"` appends one BLOCKED line; `blocked_lines` is what `crew ls` shows.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from task_progress import append_blocked, blocked_reason

from lib.clock import utc_stamp
from lib.git import GitError, output

LOCK_NAME = ".crew-worker.lock"
STALE_SECONDS = 6 * 60 * 60
BLOCKED = "BLOCKED: "


def exclude_path(tree: Path) -> Path:
    """The `info/exclude` file git consults for `tree` (shared by a repository's worktrees)."""
    raw = output(tree, ["rev-parse", "--git-path", "info/exclude"]).strip()
    path = Path(raw)
    return path if path.is_absolute() else tree / path


def write_lock(tree: Path, task: str, now: float | None = None) -> Path:
    """Write the lock and make sure git ignores it; rewriting a lock refreshes its start."""
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


def remove_lock(tree: Path) -> bool:
    """Delete the lock; True when one was there."""
    lock = tree / LOCK_NAME
    existed = lock.is_file()
    lock.unlink(missing_ok=True)
    return existed


def is_fresh(tree: Path, now: float | None = None) -> bool:
    """True when `tree` holds a lock started less than `STALE_SECONDS` ago."""
    try:
        fields = dict(line.split("=", 1) for line in (tree / LOCK_NAME).read_text(encoding="utf-8").splitlines()
                      if "=" in line)
        return (time.time() if now is None else now) - int(fields["started"]) < STALE_SECONDS
    except (OSError, KeyError, ValueError):
        return False


def blocked_lines(tasks: list[tuple[str, Path]]) -> list[str]:
    """`<task>  BLOCKED: <reason>` for each `(name, task dir)` that is blocked, after a blank line."""
    shown = [f"{label}  {BLOCKED}{reason}" for label, directory in tasks
             if (reason := blocked_reason(directory))]
    return ["", *shown] if shown else []


def main(argv: list[str], command: str) -> int:
    parser = argparse.ArgumentParser(prog=f"crew-task.py {command}")
    if command == "blocked":
        parser.add_argument("task_dir", type=Path)
        parser.add_argument("reason")
        args = parser.parse_args(argv)
        if not args.task_dir.is_dir():
            print(f"blocked: task_dir does not exist: {args.task_dir}", file=sys.stderr)
            return 1
        append_blocked(args.task_dir, args.reason)
        return 0
    parser.add_argument("action", choices=("write", "remove"))
    parser.add_argument("tree", type=Path)
    parser.add_argument("--task", default="unknown", help="task id recorded in the lock")
    args = parser.parse_args(argv)
    if not args.tree.is_dir():
        print(f"lock: no such directory: {args.tree}", file=sys.stderr)
        return 1
    if args.action == "write":
        print(write_lock(args.tree, args.task))
    else:
        remove_lock(args.tree)
    return 0
