#!/usr/bin/env python3
"""Change a task's state: gates, restore-status, reconcile, record-pr, status migration, BLOCKED, lock, gc, ship.

`crew-ls.py` only reads task state and `crew-progress.py` only appends a transition line; every other write goes
through here (`gc`: retention, `task_gc.py`; `ship`: commit to DONE, `task_ship.py`; `prepare-implement|spec`: a
stage's setup in one call, `task_prepare*.py`). `lock`, `blocked`, `worktree`, `report` and `usage` parse their own
arguments (`task_lock.py`, `task_worktrees.py`, `task_builder_report.py`, `task_usage.py`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DELEGATED = {
    "lock": "write|remove <tree> [--task ID]: the worker lock the guard hook reads",
    "blocked": "<TASK_DIR> <reason>: one BLOCKED line, shown by crew ls",
    "worktree": "pref|record|check: where the worker runs, and whether a branch may be cut here",
    "report": "save <TASK_DIR> [--range A-B] < reply: a builder's reply saved as REPORT.md, as the hook does",
    "usage": "stop < payload: a Cursor `stop` payload's token counts on its task (the cursor-usage.sh hook)",
}


def delegated(name: str, argv: list[str]) -> int:
    """Run `lock`, `blocked`, `worktree`, `report` or `usage` in the module that owns it."""
    if name == "report":
        from crew.task.task_builder_report import main as report

        return report(argv)
    if name == "usage":
        from crew.task.task_usage import main as usage

        return usage(argv)
    if name in ("lock", "blocked"):
        from crew.task.task_lock import main as lock

        return lock(argv, name)
    if argv[:1] == ["check"]:
        from crew.task.task_worktrees import check_main as check

        return check(argv[1:])
    from crew.task.task_worktrees import pref_main as preference

    return preference(argv)


def gate(args: argparse.Namespace) -> int:
    """The three transition gates; each refuses with its reason (`task_gates.py`)."""
    from crew.task.task_gates import mark_approved, mark_done, mark_implementing

    if args.command == "mark-approved":
        return mark_approved(args.task_dir)
    if args.command == "mark-implementing":
        return mark_implementing(args.task_dir, args.branch or "", args.root)
    return mark_done(args.task_dir, args.pr_url, args.force)


def restore(args: argparse.Namespace) -> int:
    """Clear a TAMPERED task: the recorded status back into the spec, or `--accept` the spec's (`task_gates.py`)."""
    from crew.task.task_gates import restore_status

    return restore_status(args.task_dir, args.accept)


def reconcile_tasks(args: argparse.Namespace) -> int:
    """Report the specs ready to mark done or open a PR, stalled and idle ones; `--apply` writes the
    ON-HOLD statuses and the PRs found on GitHub for each IMPLEMENTING task's branch."""
    from crew.task.ls_data import load_rows
    from crew.task.task_prs import CACHE_NAME, branch_prs
    from crew.task.task_report import reconcile
    from crew.task.task_state import RulesError

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
    from crew.task.task_state import normalize_all

    if not args.tasks_dir.is_dir():
        print(f"error: no tasks directory: {args.tasks_dir}", file=sys.stderr)
        return 2
    return 0 if normalize_all(args.tasks_dir, args.apply) >= 0 else 1


def record_pr(args: argparse.Namespace) -> int:
    """The PR hook: record the PR a `gh pr create` opened on its task (`task_record_pr.py`)."""
    from crew.task.task_record_pr import main as record

    return record(args.tasks_dir, sys.stdin.read())


def collect_garbage(args: argparse.Namespace) -> int:
    """Old DONE artifacts and tasks, memory session files and the legacy telemetry (`task_gc.py`)."""
    from crew.task.task_gc import main as gc

    return gc(args)


def ship(args: argparse.Namespace) -> int:
    """Commit, merge the base, re-test, push, open a draft PR and mark done, resuming a stopped run (`task_ship.py`)."""
    from crew.task.task_ship import ship_task

    if (args.task_dir is None) != args.no_task or (args.phase and args.no_task):
        print("error: give TASK_DIR or --no-task, not both and not neither (--phase needs TASK_DIR)", file=sys.stderr)
        return 2
    return ship_task(args.task_dir, args.title, args.body_file, args.base, args.repo, args.attribution, args.phase)


def add_prepare_parsers(commands) -> None:
    """`prepare-implement` and `prepare-spec`: a stage's setup in one call (`task_prepare`, `task_prepare_spec`)."""
    from crew.task.task_prepare import add_prepare_parser
    from crew.task.task_prepare import main as implement
    from crew.task.task_prepare_spec import add_prepare_spec_parser
    from crew.task.task_prepare_spec import main as spec

    add_prepare_parser(commands)
    add_prepare_spec_parser(commands)
    commands.choices["prepare-implement"].set_defaults(run=implement)
    commands.choices["prepare-spec"].set_defaults(run=spec)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crew-task.py", description=__doc__.splitlines()[0])
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
    shipper = commands.add_parser(
        "ship", help="after the owner's go: commit, merge the base, re-run ## Tests, push, open a draft PR, mark done; a re-run resumes"
    )
    shipper.add_argument("task_dir", metavar="TASK_DIR", type=Path, nargs="?")
    shipper.add_argument("--no-task", action="store_true", help="ship the current checkout's branch; no mark-done")
    shipper.add_argument("--phase", action="store_true", help="one PR of a program: record the PR, keep IMPLEMENTING; later phases' boxes may be open")
    shipper.add_argument("--title", required=True, help="the commit message and the PR title")
    shipper.add_argument("--body-file", required=True, type=Path, help="the PR description")
    shipper.add_argument("--base", required=True, help="the base branch approved at Gate 2")
    shipper.add_argument("--repo", required=True, help="the owner/repo the PR targets, approved at Gate 2")
    shipper.add_argument("--attribution", default="", help="the commit's trailer line (empty: Co-Authored-By: Claude <noreply@anthropic.com>)")
    shipper.set_defaults(run=ship)
    add_prepare_parsers(commands)
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
