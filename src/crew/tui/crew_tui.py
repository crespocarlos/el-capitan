#!/usr/bin/env python3
"""Dashboard over crew task state: ongoing tasks, a summary of tasks, PRs and issues, runs, and the cost report.

`--once` prints every view as plain text (ISSUE and PR as `#n`, child rows shown) with no Textual import; without it
the Textual app runs (the `tui` dependency group), the cells as terminal links. Filters match `crew ls`. It never
calls a model; it writes only the GitHub facts cache, and the app's `s` key runs a `crew-task.py` move its dialog
confirms. GitHub is read by the app every few minutes and on `R`, and by `--once --github`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from crew.task.ls_data import configured_scope
from crew.task.task_gc import ConfigError
from crew.tui.tui_github import fetch, load_facts, save_facts
from crew.tui.tui_model import Filters, collect, parse_filter, render
from crew.tui.tui_views import VIEWS

RUN = "uv run --group tui python -m crew.tui.crew_tui"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crew dashboard: ongoing tasks, tasks with PRs and issues, runs, cost; s runs a confirmed crew-task.py move.")
    parser.add_argument("--tasks-dir", type=Path, default=Path.home() / ".agent/tasks")
    parser.add_argument(
        "--repo",
        metavar="OWNER/NAME|here|all",
        help="one repository's tasks (default: ls.repo of ~/.agent/config.json, else here: the current repo inside one; all: every repo)",
    )
    parser.add_argument("--status", action="append", default=[], metavar="STATE", help="only tasks in STATE (repeatable)")
    parser.add_argument("--since", type=int, default=30, metavar="DAYS", help="the report window in days (30)")
    parser.add_argument("--interval", type=float, default=12.0, metavar="N", help="seconds between full refreshes (12); LIVE moves every 1.5")
    parser.add_argument("--once", action="store_true", help="print every view as plain text and exit")
    parser.add_argument("--github", action="store_true", help="with --once: read GitHub first (else the cached facts)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.interval <= 0 or args.since < 1:
        parser.error("--interval must be positive and --since at least 1")
    if args.github and not args.once:
        parser.error("--github is for --once; the app reads GitHub itself, and on R")
    try:
        states = parse_filter(" ".join(f"status:{state}" for state in args.status)).states
    except ValueError as error:
        parser.error(f"--status: {error}")
    try:
        repo = args.repo or configured_scope()  # read once, so a refresh never meets a broken config.json
    except ConfigError as error:
        print(f"crew_tui: {error}", file=sys.stderr)
        return 2
    filters = Filters(repo=repo, states=states, days=args.since)
    if args.once:
        facts = load_facts()
        views, watch = collect(args.tasks_dir, filters, facts)
        if args.github:
            save_facts(facts := fetch(watch.urls, facts, clones=watch.clones))
            views, _ = collect(args.tasks_dir, filters, facts)
        width = shutil.get_terminal_size((0, 0)).columns  # COLUMNS, else the terminal; 0 (no cut) when piped
        print("\n\n".join("\n".join(render(views[key], width)) for key in VIEWS))
        return 0
    try:
        from crew.tui.tui_app import CrewApp
    except ModuleNotFoundError as error:
        if not (error.name or "").startswith("textual"):
            raise
        print(f"crew_tui: the app needs Textual; run: {RUN}\n(--once prints the views without it)", file=sys.stderr)
        return 2
    CrewApp(args.tasks_dir, filters, args.interval).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
