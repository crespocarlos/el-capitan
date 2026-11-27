#!/usr/bin/env python3
"""Read-only dashboard over crew task state: tasks, workers and locks, and the report.

`--once` prints every view as plain text and exits, with no Textual import; without it the Textual
app runs (pinned in `tui/requirements.txt`). Filters match `crew ls`. It never writes or calls a model;
GitHub is read only for `--landed` or the app's `g` key. `crew ls --watch` is the zero-dependency view.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tui_model import VIEWS, Filters, collect, landed_for, parse_filter, render

RUN = "uv run --no-project --with-requirements tui/requirements.txt python3 tui/crew_tui.py"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only crew dashboard: tasks, workers and locks, report.")
    parser.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    parser.add_argument("--repo", metavar="OWNER/NAME|all",
                        help="one repository's tasks (default: the current repo inside one; all: every repo)")
    parser.add_argument("--status", action="append", default=[], metavar="STATE",
                        help="only tasks in STATE (repeatable)")
    parser.add_argument("--all", action="store_true", help="list DONE tasks too")
    parser.add_argument("--since", type=int, default=30, metavar="DAYS", help="the report window in days (30)")
    parser.add_argument("--interval", type=float, default=5.0, metavar="N", help="seconds between refreshes (5)")
    parser.add_argument("--once", action="store_true", help="print every view as plain text and exit")
    parser.add_argument("--landed", action="store_true", help="with --once: read each DONE task's PR on GitHub")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.interval <= 0 or args.since < 1:
        parser.error("--interval must be positive and --since at least 1")
    if args.landed and not args.once:
        parser.error("--landed is for --once; in the app, press g")
    try:
        states = parse_filter(" ".join(f"status:{state}" for state in args.status)).states
    except ValueError as error:
        parser.error(f"--status: {error}")
    filters = Filters(repo=args.repo, states=states, done=args.all, days=args.since)
    if args.once:
        landed = landed_for(args.tasks_dir, filters) if args.landed else None
        views = collect(args.tasks_dir, filters, landed)
        print("\n\n".join("\n".join(render(views[key])) for key in VIEWS))
        return 0
    try:
        from tui_app import CrewApp
    except ModuleNotFoundError as error:
        if not (error.name or "").startswith("textual"):
            raise
        print(f"crew_tui: the app needs Textual; run: {RUN}\n(--once prints the views without it)", file=sys.stderr)
        return 2
    CrewApp(args.tasks_dir, filters, args.interval).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
