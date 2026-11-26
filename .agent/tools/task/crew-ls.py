#!/usr/bin/env python3
"""List crew task state (read only) without failing on malformed task metadata.

Modes: the table, `--md`, `--tsv`, `--json`, `--watch [--interval N]`; `--all` adds done specs with
`landed: yes | no | unknown`; `--limit`/`--max-chars` bound it; `--status-file SPEC.md` prints one
status; `--reconcile` reports ready, stalled and idle specs (`transitions.json`). Writes: `crew-task.py`.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from ls_data import DEFAULT_INTERVAL, LandedCache, load_rows, watch
from task_report import print_listing, print_status_file, reconcile
from task_state import RulesError

from lib.output import DEFAULT_MAX_CHARS

SUMMARY = "List task state: table, --md, --tsv, or --json; --reconcile reports. Writes: crew-task.py."


def make_parser() -> argparse.ArgumentParser:
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
                        help="report ready, stalled, and idle specs (crew-task.py reconcile --apply writes)")
    parser.add_argument("--status-file", metavar="SPEC.md",
                        help="print the Status value of one spec (single reader for hooks)")
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    if args.status_file:
        return print_status_file(args.status_file)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.max_chars < 1:
        parser.error("--max-chars must be at least 1")
    if args.cost:
        from task_progress import print_cost

        return print_cost(args.tasks_dir)
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
        return reconcile(rows, False)
    except RulesError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
