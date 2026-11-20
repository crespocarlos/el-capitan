#!/usr/bin/env python3
"""List crew task state without failing on malformed task metadata.

(default)    table of open specs, then a count of done specs; --all lists done specs; --md prints
             a Markdown table; --tsv prints the machine format (slug, branch, status, verdict, age).
--reconcile  report IMPLEMENTING specs ready to open a PR (all criteria checked, review pass or warn),
             stalled IMPLEMENTING specs, and idle DRAFTING/APPROVED specs (>14d).
--apply      with --reconcile, write ON-HOLD (naming the prior status) for idle specs and log to
             PROGRESS.md. Never sets DONE (crew open pr does, via --mark-done), ABANDONED or approval.
--mark-implementing TASK_DIR   set IMPLEMENTING when crew implement starts; only from APPROVED.
--mark-done TASK_DIR --pr-url URL [--branch NAME] [--force]
             set DONE from crew open pr; only from IMPLEMENTING, with all criteria checked, a review
             pass or warn, the reviewed commit as an ancestor of HEAD, and --branch matching the
             task's branch. --force is a user-invoked escape hatch that skips those evidence checks.
Rules live in transitions.json and are tried in file order; the first match wins.

This file is the argparse entry point only: the record, the writes, and the reconcile rules live in
`task_state.py`, and rendering plus the gates live in `task_report.py`. `Path(__file__).resolve()`
follows the installed `~/.agent/bin` symlink back to this directory, so the siblings are found from
either invocation path.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TASK_DIR = Path(__file__).resolve().parent
if str(_TASK_DIR) not in sys.path:
    sys.path.insert(0, str(_TASK_DIR))

from task_gates import mark_approved, mark_done, mark_implementing  # noqa: E402
from task_report import (  # noqa: E402
    load_rows,
    print_listing,
    print_status_file,
    reconcile,
)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    parser.add_argument("--tsv", action="store_true",
                        help="tab-separated slug, branch, status, verdict, age")
    parser.add_argument("--md", action="store_true", help="Markdown table, for pasting into chat")
    parser.add_argument("--all", action="store_true", help="list done specs too")
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--mark-approved", metavar="TASK_DIR",
                        help="record Gate 1: set APPROVED from DRAFTING")
    parser.add_argument("--status-file", metavar="SPEC.md",
                        help="print the Status value of one spec (single reader for hooks)")
    parser.add_argument("--mark-implementing", metavar="TASK_DIR",
                        help="set IMPLEMENTING when crew implement starts")
    parser.add_argument("--mark-done", metavar="TASK_DIR",
                        help="set DONE after crew open pr; needs --pr-url")
    parser.add_argument("--pr-url")
    parser.add_argument("--branch", help="current branch; must match the task's branch")
    parser.add_argument("--force", action="store_true",
                        help="skip the evidence checks in --mark-done")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.status_file:
        return print_status_file(args.status_file)
    if args.mark_approved:
        sys.exit(mark_approved(args.mark_approved))
    if args.mark_implementing:
        sys.exit(mark_implementing(args.mark_implementing, args.branch or ""))
    if args.mark_done:
        if not args.pr_url:
            parser.error("--mark-done requires --pr-url")
        sys.exit(mark_done(args.mark_done, args.pr_url, args.branch, args.force))
    if args.apply and not args.reconcile:
        parser.error("--apply requires --reconcile")
    rows = load_rows(args.tasks_dir)
    if not args.reconcile:
        print_listing(rows, args)
        return 0
    return reconcile(rows, args.apply)


if __name__ == "__main__":
    sys.exit(main() or 0)
