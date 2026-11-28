#!/usr/bin/env python3
"""The owner's and the hooks' task commands: the moves the TUI offers, restore-status, reconcile, record-pr, status
migration, gc, and the hook rules `report` and `usage`.

Agents use `crew-tool.py` (a move is `task-transition`); `mark-done --force`, `restore-status --accept`, `gc` and
`normalize-status` are the owner's. `crew-ls.py` only reads task state. `worktree`, `report` and `usage` parse their
own arguments (`task_worktrees.py`, `task_builder_report.py`, `task_usage.py`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from crew.lib.errors import ToolError

DELEGATED = {
    "worktree": "pref|record|check: where the worker runs, and whether a branch may be cut here",
    "report": "save <TASK_DIR> [--range A-B] < reply: a builder's reply saved as REPORT.md, as the hook does",
    "usage": "stop < event: a stop event's token counts on its task (the usage.sh hook rule)",
}


def delegated(name: str, argv: list[str]) -> int:
    """Run `worktree`, `report` or `usage` in the module that owns it."""
    if name == "report":
        from crew.core.task.task_builder_report import main as report

        return report(argv)
    if name == "usage":
        from crew.core.task.task_usage import main as usage

        return usage(argv)
    if argv[:1] == ["check"]:
        from crew.core.task.task_worktrees import check_main as check

        return check(argv[1:])
    from crew.core.task.task_worktrees import pref_main as preference

    return preference(argv)


def said(run: object) -> int:
    """Print what a core write said, or `error: <message>` on stderr with its exit."""
    try:
        line = run() if callable(run) else ""
    except ToolError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit
    if line:
        print(line)
    return 0


def gate(args: argparse.Namespace) -> int:
    """The three transition gates and BLOCKED; each refuses with its reason (`task_gates.py`, `task_lock.py`)."""
    from crew.core.task.task_gates import mark_approved, mark_done, mark_implementing
    from crew.core.task.task_lock import blocked

    if args.command == "mark-approved":
        return said(lambda: mark_approved(args.task_dir))
    if args.command == "mark-implementing":
        return said(lambda: mark_implementing(args.task_dir, args.branch or "", args.root))
    if args.command == "blocked":
        return said(lambda: blocked(Path(args.task_dir), args.reason))
    return said(lambda: mark_done(args.task_dir, args.pr_url, args.force))


def restore(args: argparse.Namespace) -> int:
    """Clear a TAMPERED task: the recorded status back into the spec, or `--accept` the spec's (`task_gates.py`)."""
    from crew.core.task.task_gates import restore_status

    return said(lambda: restore_status(args.task_dir, args.accept))


def reconcile_tasks(args: argparse.Namespace) -> int:
    """Report the specs ready to mark done or open a PR, stalled and idle ones; `--apply` writes the
    ON-HOLD statuses and the PRs found on GitHub for each IMPLEMENTING task's branch."""
    from crew.core.task.ls_data import load_rows
    from crew.core.task.task_prs import CACHE_NAME, branch_prs
    from crew.core.task.task_report import reconcile
    from crew.core.task.task_state import RulesError

    if args.pr_budget is not None and args.pr_budget <= 0:
        print("error: --pr-budget must be positive", file=sys.stderr)
        return 2
    cache = args.tasks_dir.parent / CACHE_NAME
    try:
        return reconcile(load_rows(args.tasks_dir), args.apply, lambda rows: branch_prs(rows, cache, args.pr_budget, write=args.apply))
    except RulesError as error:
        print(str(error), file=sys.stderr)
        return 2


def normalize(args: argparse.Namespace) -> int:
    """Rewrite legacy lowercase status tokens to their canonical spelling (a preview without --apply)."""
    from crew.core.task.task_state import normalize_all

    if not args.tasks_dir.is_dir():
        print(f"error: no tasks directory: {args.tasks_dir}", file=sys.stderr)
        return 2
    return 0 if normalize_all(args.tasks_dir, args.apply) >= 0 else 1


def record_pr(args: argparse.Namespace) -> int:
    """The PR hook: record the PR a `gh pr create` opened on its task (`task_record_pr.py`)."""
    from crew.core.task.task_record_pr import main as record

    return record(args.tasks_dir, sys.stdin.read())


def collect_garbage(args: argparse.Namespace) -> int:
    """Old DONE artifacts and tasks, memory session files and the legacy telemetry (`task_gc.py`)."""
    from crew.core.task.task_gc import main as gc

    return gc(args)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crew-task.py", description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    approved = commands.add_parser("mark-approved", help="Gate 1: DRAFTING to APPROVED")
    implementing = commands.add_parser("mark-implementing", help="APPROVED to IMPLEMENTING when crew implement starts")
    done = commands.add_parser("mark-done", help="IMPLEMENTING to DONE once a PR is open; records the PR")
    for sub in (approved, implementing, done):
        sub.add_argument("task_dir", metavar="TASK_DIR")
        sub.set_defaults(run=gate)
    implementing.add_argument(
        "--branch", help="the branch being implemented, recorded in .task-id (default: the --root checkout's branch, never the default branch)"
    )
    implementing.add_argument("--root", type=Path, default=None, help="the implementation checkout, recorded as .task-id worktree (default: the cwd)")
    done.add_argument("--pr-url", required=True, help="the GitHub PR URL to add to the task's PR list (with --force, any note)")
    done.add_argument("--force", action="store_true", help="skip the evidence checks (user-invoked only)")
    restorer = commands.add_parser("restore-status", help="clear a TAMPERED task: write the gate-stamped status back into SPEC.md")
    restorer.add_argument("task_dir", metavar="TASK_DIR")
    restorer.add_argument(
        "--accept", metavar="NOTE", help="the owner only, in their own terminal (refused in an agent shell): keep the spec's status, recorded with this note"
    )
    restorer.set_defaults(run=restore)
    for name, run, text in (
        ("reconcile", reconcile_tasks, "report ready, stalled and idle specs; record branch PRs"),
        ("normalize-status", normalize, "rewrite legacy lowercase status tokens"),
    ):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--apply", action="store_true", help="write the changes (default: report only)")
        sub.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
        sub.set_defaults(run=run)
        if name == "reconcile":
            sub.add_argument(
                "--pr-budget", type=float, default=None, metavar="SECONDS", help="stop asking GitHub for branch PRs after SECONDS (the session-start hook: 3)"
            )
    recorder = commands.add_parser("record-pr", help="the PR hook: record a `gh pr create` PR on its task (stdin)")
    recorder.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    recorder.set_defaults(run=record_pr)
    collect = commands.add_parser("gc", help="retention: old DONE artifacts and tasks, session files, legacy telemetry (policy: ~/.agent/config.json)")
    collect.add_argument("--apply", action="store_true", help="remove and archive (default: list what would go)")
    collect.add_argument("--json", action="store_true", help="the selected paths as a JSON array (with --apply, an archived task names its tarball)")
    collect.add_argument("--only", choices=["telemetry"], help="select only the legacy ~/.agent/telemetry and the hook logs' old lines")
    collect.add_argument("--tasks-dir", type=Path, default=None, help="default ~/.agent/tasks")
    collect.set_defaults(run=collect_garbage)
    blocker = commands.add_parser("blocked", help="one BLOCKED line, shown by crew ls")
    blocker.add_argument("task_dir", metavar="TASK_DIR")
    blocker.add_argument("reason")
    blocker.set_defaults(run=gate)
    for name, text in DELEGATED.items():
        commands.add_parser(name, help=text, add_help=False)
    # No abbreviated options: `--acc` would be `--accept` past the owner-only guard, which matches words as written.
    for each in (parser, *commands.choices.values()):
        each.allow_abbrev = False
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] and arguments[0] in DELEGATED:
        return delegated(arguments[0], arguments[1:])
    args = make_parser().parse_args(arguments)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
