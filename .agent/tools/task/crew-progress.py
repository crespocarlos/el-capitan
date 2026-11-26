#!/usr/bin/env python3
"""Append a pipeline transition to PROGRESS.md: crew-progress.py <TASK_DIR> "<FROM> → <TO>".

CREW_WORKFLOW and CREW_MEMBER, when set, add a JSON suffix with the step, workflow and crew fields.
Gates and report checks are `crew-verify.py`; lock, BLOCKED and worktree writes are `crew-task.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_progress import append_transition


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a pipeline transition to PROGRESS.md.")
    parser.add_argument("task_dir", help="Path to the task directory")
    parser.add_argument("transition", help='Transition string e.g. "APPROVED → IMPLEMENTING"')
    args = parser.parse_args()
    if not Path(args.task_dir).is_dir():
        parser.error(f"not a task directory: {args.task_dir}")
    try:
        append_transition(Path(args.task_dir), args.transition)
    except FileNotFoundError as error:
        print(f"log-progress: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
