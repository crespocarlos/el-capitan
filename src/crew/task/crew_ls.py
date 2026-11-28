#!/usr/bin/env python3
"""List crew task state (read only) without failing on malformed task metadata.

Modes: the table, `--md`, `--json`, `--watch [--interval N]`, `--report [--since Nd]`; `--repo` (else
`ls.repo` of `~/.agent/config.json`) and `--status` filter; `--all` adds done specs with `landed: yes | no | unknown`; `--limit`/`--max-chars`
bound it; `--status-file SPEC.md` prints one status; `--reconcile` reports ready, stalled and idle
specs (`transitions.json`). Writes: `crew-task.py`.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from crew.lib.output import DEFAULT_MAX_CHARS
from crew.task.ls_data import DEFAULT_INTERVAL, LandedCache, load_rows, repo_filter, select, watch
from crew.task.task_gc import ConfigError
from crew.task.task_report import print_listing, print_status_file, reconcile
from crew.task.task_state import RulesError
from crew.task.task_status import StatusError, token

SUMMARY = "List task state: table, --md, --json or --report; --reconcile reports. Writes: crew-task.py."


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=SUMMARY)
    parser.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    parser.add_argument("--md", action="store_true", help="Markdown table, for pasting into chat")
    parser.add_argument(
        "--json", action="store_true", help='one JSON object {"items": [...], "returned", "total", "truncated"} on stdout, diagnostics on stderr'
    )
    parser.add_argument("--all", action="store_true", help="list done specs too")
    parser.add_argument(
        "--repo",
        metavar="OWNER/NAME|here|all",
        help="one repository's tasks (default: ls.repo of ~/.agent/config.json, else here: the current repo inside one; all: every repo)",
    )
    parser.add_argument("--status", action="append", metavar="STATE", help="only tasks in STATE (repeatable); shows stale IMPLEMENTING tasks unfolded")
    parser.add_argument("--report", action="store_true", help="tasks opened and closed, verdicts, findings, stage costs, tool failures")
    parser.add_argument("--since", default="30d", metavar="Nd", help="the --report window (30d)")
    parser.add_argument("--cost", action="store_true", help="print each task's recorded stage cost lines")
    parser.add_argument("--watch", action="store_true", help="redraw the table until Ctrl-C")
    parser.add_argument("--interval", type=float, default=None, metavar="N", help="seconds between redraws (3)")
    parser.add_argument("--limit", type=int, default=None, help="show at most N tasks")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="truncate output past N chars with a marker")
    parser.add_argument("--reconcile", action="store_true", help="report ready, stalled, and idle specs (crew-task.py reconcile --apply writes)")
    parser.add_argument("--status-file", metavar="SPEC.md", help="print the Status value of one spec (single reader for hooks)")
    return parser


def report(args: argparse.Namespace, repos: set[str] | None) -> int:
    """`--report`: one screen, or `--json`, over the filtered rows."""
    from crew.task.ls_report import gather, render, since_days

    try:
        days = since_days(args.since)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    data = gather(select(load_rows(args.tasks_dir), repos, args.status), days)
    scope = "repo " + ", ".join(sorted(repos)) if repos else "every repo"
    print(json.dumps(data) if args.json else "\n".join(render(data, scope)))
    return 0


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
        from crew.task.task_cost import print_cost

        return print_cost(args.tasks_dir)
    if args.interval is not None and not args.watch:
        parser.error("--interval requires --watch")
    if args.watch and (args.json or args.reconcile or args.report or (args.interval is not None and args.interval <= 0)):
        parser.error("--watch redraws the table: no --json, --report or --reconcile, and --interval must be positive")
    for state in args.status or []:
        try:
            token(state)
        except StatusError as error:
            parser.error(f"--status: {error}")
    try:
        repos = repo_filter(args.repo)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.report:
        return report(args, repos)
    scope = f"repo {', '.join(sorted(repos))} (--repo all lists every repo)" if repos else "every repo"
    try:
        if args.watch:
            signal.signal(signal.SIGINT, signal.default_int_handler)
            cache = LandedCache()  # `--watch --all` reads each DONE task's PR at most once a minute
            return watch(
                lambda: print_listing(select(load_rows(args.tasks_dir), repos, args.status), args, cache.lines, scope), args.interval or DEFAULT_INTERVAL
            )
        rows = load_rows(args.tasks_dir)
        if not args.reconcile:
            if args.repo and repos and not any(r.repo for r in select(rows, repos)):
                print(f"no task recorded for {args.repo}; --repo all lists every one", file=sys.stderr)
            print_listing(select(rows, repos, args.status), args, scope=scope)
            return 0
        return reconcile(rows, False)
    except RulesError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
