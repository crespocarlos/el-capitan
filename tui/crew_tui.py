#!/usr/bin/env python3
"""Dashboard over crew task state: tasks, workers and locks, and the report.

`--once` prints every view as plain text (ISSUE and PR as `#n`) with no Textual import; without it the
Textual app runs (pinned in `tui/requirements.txt`), the cells as terminal links. Filters match `crew ls`.
It never calls a model or writes a file itself: the app's `s` key runs `crew-task.py` after a confirm dialog.
GitHub is read only for `--landed` or the app's `g` key.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import tui_bootstrap  # noqa: F401

from ls_data import configured_scope
from task_gc import ConfigError

from tui_model import VIEWS, Filters, collect, landed_for, parse_filter, render

RUN = "uv run --no-project --with-requirements tui/requirements.txt python3 tui/crew_tui.py"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crew dashboard: tasks, workers and locks, report; "
                                                 "s runs a confirmed crew-task.py move.")
    parser.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    parser.add_argument("--repo", metavar="OWNER/NAME|here|all",
                        help="one repository's tasks (default: ls.repo of ~/.agent/config.json, else here: "
                             "the current repo inside one; all: every repo)")
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
    try:
        repo = args.repo or configured_scope()  # read once, so a refresh never meets a broken config.json
    except ConfigError as error:
        print(f"crew_tui: {error}", file=sys.stderr)
        return 2
    filters = Filters(repo=repo, states=states, done=args.all, days=args.since)
    if args.once:
        landed = landed_for(args.tasks_dir, filters) if args.landed else None
        views = collect(args.tasks_dir, filters, landed)
        width = shutil.get_terminal_size((0, 0)).columns  # COLUMNS, else the terminal; 0 (no cut) when piped
        print("\n\n".join("\n".join(render(views[key], width)) for key in VIEWS))
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
