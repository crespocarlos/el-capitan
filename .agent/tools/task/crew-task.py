#!/usr/bin/env python3
"""Change a task's state: the transition gates, reconcile, status migration, BLOCKED, lock, worktree, gc.

`crew-ls.py` only reads task state and `crew-progress.py` only appends a transition line; every
other write goes through here (`gc`: retention, `task_gc.py`). `lock`, `blocked` and `worktree`
parse their own arguments (`task_lock.py`, `task_worktrees.py`); see each one's `--help`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

DELEGATED = {
    "lock": "write|remove <tree> [--task ID]: the worker lock the guard hook reads",
    "blocked": "<TASK_DIR> <reason>: one BLOCKED line, shown by crew ls",
    "worktree": "pref|record|check: where the worker runs, and whether a branch may be cut here",
}


def delegated(name: str, argv: list[str]) -> int:
    """Run `lock`, `blocked` or `worktree` in the module that owns it."""
    if name in ("lock", "blocked"):
        from task_lock import main as lock

        return lock(argv, name)
    if argv[:1] == ["check"]:
        from task_worktrees import check_main as check

        return check(argv[1:])
    from task_worktrees import pref_main as preference

    return preference(argv)


def gate(args: argparse.Namespace) -> int:
    """The three transition gates; each refuses with its reason (`task_gates.py`)."""
    from task_gates import mark_approved, mark_done, mark_implementing

    if args.command == "mark-approved":
        return mark_approved(args.task_dir)
    if args.command == "mark-implementing":
        return mark_implementing(args.task_dir, args.branch or "")
    return mark_done(args.task_dir, args.pr_url, args.branch, args.force)


def reconcile_tasks(args: argparse.Namespace) -> int:
    """Report ready, stalled and idle specs; `--apply` writes ON-HOLD for the idle ones."""
    from ls_data import load_rows
    from task_report import reconcile
    from task_state import RulesError

    try:
        return reconcile(load_rows(args.tasks_dir), args.apply)
    except RulesError as error:
        print(str(error), file=sys.stderr)
        return 2


def normalize(args: argparse.Namespace) -> int:
    """Rewrite legacy lowercase status tokens to their canonical spelling (a preview without --apply)."""
    from task_state import normalize_all

    if not args.tasks_dir.is_dir():
        print(f"error: no tasks directory: {args.tasks_dir}", file=sys.stderr)
        return 2
    return 0 if normalize_all(args.tasks_dir, args.apply) >= 0 else 1


def collect_garbage(args: argparse.Namespace) -> int:
    """Old DONE artifacts and tasks, memory session files and the legacy telemetry (`task_gc.py`)."""
    from task_gc import main as gc

    return gc(args)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crew-task.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    approved = commands.add_parser("mark-approved", help="Gate 1: DRAFTING to APPROVED")
    implementing = commands.add_parser("mark-implementing", help="APPROVED to IMPLEMENTING when crew implement starts")
    done = commands.add_parser("mark-done", help="IMPLEMENTING to DONE after crew open pr")
    for sub in (approved, implementing, done):
        sub.add_argument("task_dir", metavar="TASK_DIR")
        sub.set_defaults(run=gate)
    for sub in (implementing, done):
        sub.add_argument("--branch", help="current branch; must match the task's branch")
    done.add_argument("--pr-url", required=True, help="the PR URL to record")
    done.add_argument("--force", action="store_true", help="skip the evidence checks (user-invoked only)")
    for name, run, text in (("reconcile", reconcile_tasks, "report ready, stalled and idle specs"),
                            ("normalize-status", normalize, "rewrite legacy lowercase status tokens")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--apply", action="store_true", help="write the changes (default: report only)")
        sub.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
        sub.set_defaults(run=run)
    collect = commands.add_parser("gc", help="retention: old DONE artifacts and tasks, session files, legacy telemetry "
                                  "(policy: ~/.agent/config.json)")
    collect.add_argument("--apply", action="store_true", help="remove and archive (default: list what would go)")
    collect.add_argument("--json", action="store_true",
                         help="the selected paths as a JSON array (with --apply, an archived task names its tarball)")
    collect.add_argument("--only", choices=["telemetry"], help="select only the legacy ~/.agent/telemetry")
    collect.add_argument("--tasks-dir", type=Path, default=None, help="default ~/.agent/tasks")
    collect.set_defaults(run=collect_garbage)
    for name, text in DELEGATED.items():
        commands.add_parser(name, help=text, add_help=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] and arguments[0] in DELEGATED:
        return delegated(arguments[0], arguments[1:])
    args = make_parser().parse_args(arguments)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
