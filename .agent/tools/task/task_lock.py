"""`crew-progress.py lock`: the worker lock a live builder holds on its tree, and the BLOCKED line.

The lock is the file `<tree root>/.crew-worker.lock`, two `key=value` lines: `task=<id>` and
`started=<epoch seconds>` (plus `started_at=<UTC time>` for people). The guard hook
`.claude/hooks/guard/worker-tree.sh` reads it from bash, which is why the start is an integer:
a lock older than `STALE_SECONDS` is stale and no longer denies anything. The file is excluded
through `.git/info/exclude`, so it never shows in a status or a commit.

    crew-progress.py lock write <tree> --task <id>     dispatch: the orchestrator writes it
    crew-progress.py lock remove <tree>                exit: the builder removes it
    crew-progress.py blocked <TASK_DIR> "<reason>"     one `BLOCKED: <reason>` line in PROGRESS.md

`blocked_reason` is what `crew ls` shows: the last BLOCKED line, unless a later line (the next
stage's transition or `stage_start`) follows it; trailing `METRIC:` and `WORKTREE:` lines are skipped.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lib.git import GitError, output

LOCK_NAME = ".crew-worker.lock"
STALE_SECONDS = 6 * 60 * 60
BLOCKED = "BLOCKED: "
NEUTRAL = ("METRIC:", "WORKTREE:")  # audit and preference lines: they never end a block (a stage_start does)


def exclude_path(tree: Path) -> Path:
    """The `info/exclude` file git consults for `tree` (shared by a repository's worktrees)."""
    raw = output(tree, ["rev-parse", "--git-path", "info/exclude"]).strip()
    path = Path(raw)
    return path if path.is_absolute() else tree / path


def write_lock(tree: Path, task: str, now: float | None = None) -> Path:
    """Write the lock and make sure git ignores it; rewriting a lock refreshes its start."""
    moment = time.time() if now is None else now
    stamp = datetime.fromtimestamp(moment, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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


def write_blocked(task_dir: Path, reason: str) -> None:
    """Append one `BLOCKED: <reason>` line; a reason spanning lines is collapsed to one."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (task_dir / "PROGRESS.md").open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {BLOCKED}{' '.join(reason.split())}\n")


def blocked_reason(task_dir: Path) -> str:
    """The reason of the last BLOCKED line when no later line follows it, else an empty string."""
    try:
        lines = [line for line in (task_dir / "PROGRESS.md").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    except OSError:
        return ""
    for line in reversed(lines):
        body = line.split("] ", 1)[-1]
        if body.startswith(NEUTRAL) and "stage_start" not in body:
            continue
        return body[len(BLOCKED):].strip() if body.startswith(BLOCKED) else ""
    return ""


def blocked_lines(tasks: list[tuple[str, Path]]) -> list[str]:
    """`<task>  BLOCKED: <reason>` for each `(name, task dir)` that is blocked, after a blank line."""
    shown = [f"{label}  {BLOCKED}{reason}" for label, directory in tasks
             if (reason := blocked_reason(directory))]
    return ["", *shown] if shown else []


def main(argv: list[str], command: str) -> int:
    parser = argparse.ArgumentParser(prog=f"crew-progress.py {command}")
    if command == "blocked":
        parser.add_argument("task_dir", type=Path)
        parser.add_argument("reason")
        args = parser.parse_args(argv)
        if not args.task_dir.is_dir():
            print(f"blocked: task_dir does not exist: {args.task_dir}", file=sys.stderr)
            return 1
        write_blocked(args.task_dir, args.reason)
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
