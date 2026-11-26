#!/usr/bin/env python3
"""crew-progress.py — append a pipeline transition to PROGRESS.md.

Usage: crew-progress.py <TASK_DIR> "<FROM> → <TO>"
Example: crew-progress.py ~/.agent/tasks/repo/branch/slug "APPROVED → IMPLEMENTING"

Reads CREW_WORKFLOW and CREW_MEMBER from environment; if either is set,
appends a JSON suffix with step, workflow, and crew fields.

Five subcommands share this entry so no new command exists (a first argument of `verify`,
`report-check`, `lock`, `blocked` or `worktree` selects one; a task directory is never named that):
  crew-progress.py worktree pref|record ...        where the worker runs, asked once (task_worktree_pref.py)
  crew-progress.py worktree check <tree>           ok | on-feature-branch (4) | dirty (5) before a branch is cut (task_worktree_check.py)
  crew-progress.py verify [--task-dir DIR] ...     run the repo's gates as its CI does (task_verify.py)
  crew-progress.py report-check REPORT.md [...]    check a builder report against them (task_report_check.py)
  crew-progress.py lock write|remove <tree> ...    the worker lock the guard hook reads (task_lock.py)
  crew-progress.py blocked <TASK_DIR> "<reason>"   one `BLOCKED: <reason>` line, shown by `crew ls`
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_TASK_DIR = Path(__file__).resolve().parent
for _path in (_TASK_DIR.parent, _TASK_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def subcommand(name: str, argv: list) -> int:
    """Run a subcommand; imported late so a plain transition loads none of them."""
    if name in ("lock", "blocked"):
        from task_lock import main as run_lock
        return run_lock(argv, name)
    if name == "verify":
        from task_verify import main as run
    elif name == "worktree" and argv[:1] == ["check"]:
        from task_worktree_check import main as run
        return run(argv[1:])
    elif name == "worktree":
        from task_worktree_pref import main as run
    else:
        from task_report_check import main as run
    return run(argv)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("verify", "report-check", "lock", "blocked", "worktree"):
        return subcommand(sys.argv[1], sys.argv[2:])
    parser = argparse.ArgumentParser(
        description="Append a pipeline transition to PROGRESS.md."
    )
    parser.add_argument("task_dir", help="Path to the task directory")
    parser.add_argument("transition", help='Transition string e.g. "APPROVED → IMPLEMENTING"')
    args = parser.parse_args()

    task_dir = Path(args.task_dir)
    transition = args.transition

    if not task_dir.is_dir():
        print(f"log-progress: task_dir does not exist: {task_dir}", file=sys.stderr)
        return 1

    wf = os.environ.get("CREW_WORKFLOW", "")
    crew = os.environ.get("CREW_MEMBER", "")

    suffix = ""
    if wf or crew:
        step = transition.split("→", 1)[-1].strip()
        wf_or_none = wf if wf else None
        crew_or_none = crew if crew else None
        suffix = " " + json.dumps(
            {"step": step, "workflow": wf_or_none, "crew": crew_or_none},
            separators=(",", ":"),
        )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] TRANSITION: {transition}{suffix}\n"

    with (task_dir / "PROGRESS.md").open("a", encoding="utf-8") as handle:
        handle.write(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
