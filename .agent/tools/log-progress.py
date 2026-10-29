#!/usr/bin/env python3
"""log-progress.py — append a pipeline transition to PROGRESS.md.

Usage: log-progress.py <TASK_DIR> "<FROM> → <TO>"
Example: log-progress.py ~/.agent/tasks/repo/branch/slug "APPROVED → IMPLEMENTING"

Reads CREW_WORKFLOW and CREW_MEMBER from environment; if either is set,
appends a JSON suffix with step, workflow, and crew fields.
"""
import argparse
import json
import os
import sys
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(
        description="Append a pipeline transition to PROGRESS.md."
    )
    parser.add_argument("task_dir", help="Path to the task directory")
    parser.add_argument("transition", help='Transition string e.g. "APPROVED → IMPLEMENTING"')
    args = parser.parse_args()

    task_dir = args.task_dir
    transition = args.transition

    if not os.path.isdir(task_dir):
        print(f"log-progress: task_dir does not exist: {task_dir}", file=sys.stderr)
        sys.exit(1)

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

    progress_path = os.path.join(task_dir, "PROGRESS.md")
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    main()
