#!/usr/bin/env python3
"""List crew task state without failing on malformed task metadata.

Modes: the table (default), `--md` (Markdown, for pasting into chat), `--tsv` (slug, branch,
status, verdict, age), `--json` (machine-readable array), `--watch [--interval N]` (the table
redrawn every N seconds, default 3, until Ctrl-C; it only reads). `--all` includes done specs and shows
`landed: yes | no | unknown` for each (a PR read, see `ls_landed.py`);
`--limit` and `--max-chars` bound a long listing, and `--status-file SPEC.md` prints one spec's
`## Status` value.

`--reconcile` reports IMPLEMENTING specs ready for a PR, stalled ones, and idle DRAFTING/APPROVED
specs; `--apply` writes ON-HOLD for the idle ones and logs it. `--mark-approved`,
`--mark-implementing`, and `--mark-done` are the three transition gates; rules live in
`transitions.json`, tried in file order, first match wins.

This file is the argparse entry point only: the record, the writes, and the reconcile rules live in
`task_state.py`, and rendering plus the gates live in `task_report.py` and `task_gates.py`.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

_TASK_DIR = Path(__file__).resolve().parent
for _path in (_TASK_DIR.parent, _TASK_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from lib.output import DEFAULT_MAX_CHARS  # noqa: E402
from task_gates import mark_approved, mark_done, mark_implementing  # noqa: E402
from task_normalize import normalize_all  # noqa: E402
from ls_data import DEFAULT_INTERVAL, LandedCache, load_rows, watch  # noqa: E402
from task_report import (  # noqa: E402
    print_listing,
    print_status_file,
    reconcile,
)
from task_state import RulesError  # noqa: E402

SUMMARY = "List task state: table, --md, --tsv, or --json; reconcile and transition gates."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=SUMMARY)
    parser.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    parser.add_argument("--tsv", action="store_true",
                        help="tab-separated slug, branch, status, verdict, age")
    parser.add_argument("--md", action="store_true", help="Markdown table, for pasting into chat")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable JSON array on stdout, diagnostics on stderr")
    parser.add_argument("--all", action="store_true", help="list done specs too")
    parser.add_argument("--cost", action="store_true",
                        help="print each task's recorded stage cost lines")
    parser.add_argument("--watch", action="store_true", help="redraw the table until Ctrl-C")
    parser.add_argument("--interval", type=float, default=None, metavar="N", help="seconds between redraws (3)")
    parser.add_argument("--limit", type=int, default=None, help="show at most N tasks")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help="truncate output past N chars with a marker")
    parser.add_argument("--reconcile", action="store_true",
                        help="report ready, stalled, and idle specs")
    parser.add_argument("--apply", action="store_true",
                        help="with --reconcile, write ON-HOLD for idle specs")
    parser.add_argument("--mark-approved", metavar="TASK_DIR",
                        help="record Gate 1: set APPROVED from DRAFTING")
    parser.add_argument("--status-file", metavar="SPEC.md",
                        help="print the Status value of one spec (single reader for hooks)")
    parser.add_argument("--mark-implementing", metavar="TASK_DIR",
                        help="set IMPLEMENTING when crew implement starts")
    parser.add_argument("--mark-done", metavar="TASK_DIR",
                        help="set DONE after crew open pr; needs --pr-url")
    parser.add_argument("--pr-url", help="PR URL recorded by --mark-done")
    parser.add_argument("--branch", help="current branch; must match the task's branch")
    parser.add_argument("--force", action="store_true",
                        help="skip the evidence checks in --mark-done")
    parser.add_argument("--normalize-status", action="store_true",
                        help="rewrite a legacy lowercase status token to its canonical spelling")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.status_file:
        return print_status_file(args.status_file)
    if args.mark_approved:
        return mark_approved(args.mark_approved)
    if args.mark_implementing:
        return mark_implementing(args.mark_implementing, args.branch or "")
    if args.mark_done:
        if not args.pr_url:
            parser.error("--mark-done requires --pr-url")
        return mark_done(args.mark_done, args.pr_url, args.branch, args.force)
    if args.apply and not args.reconcile and not args.normalize_status:
        parser.error("--apply requires --reconcile or --normalize-status")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.max_chars < 1:
        parser.error("--max-chars must be at least 1")
    if args.cost:
        from task_cost import print_cost

        return print_cost(args.tasks_dir)
    if args.normalize_status:
        if not args.tasks_dir.is_dir():
            print(f"error: no tasks directory: {args.tasks_dir}", file=sys.stderr)
            return 2
        return 0 if normalize_all(args.tasks_dir, args.apply) >= 0 else 1
    if args.interval is not None and not args.watch:
        parser.error("--interval requires --watch")
    if args.watch and (args.json or args.tsv or args.reconcile or (args.interval is not None and args.interval <= 0)):
        parser.error("--watch redraws the table: no --json, --tsv or --reconcile, and --interval must be positive")
    try:
        if args.watch:
            signal.signal(signal.SIGINT, signal.default_int_handler)
            cache = LandedCache()  # `--watch --all` reads each DONE task's PR at most once a minute
            return watch(lambda: print_listing(load_rows(args.tasks_dir), args, cache.lines), args.interval or DEFAULT_INTERVAL)
        rows = load_rows(args.tasks_dir)
        if not args.reconcile:
            print_listing(rows, args)
            return 0
        return reconcile(rows, args.apply)
    except RulesError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
