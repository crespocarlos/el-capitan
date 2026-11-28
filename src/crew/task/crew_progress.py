#!/usr/bin/env python3
"""Append a pipeline step to PROGRESS.md: crew-progress.py <TASK_DIR> "<FROM> → <TO>", e.g. "IMPLEMENTING → REVIEW".

A progress note, never a status: a text whose target is a status token, or that carries the gate stamp, is refused
with exit 2, since only `crew-task.py`'s gates record a status (`task_record.forged_transition`). CREW_WORKFLOW and
CREW_MEMBER, when set, add a JSON suffix with the step, workflow and crew fields.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from crew.task.task_progress import append_transition
from crew.task.task_record import forged_transition


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a pipeline step to PROGRESS.md (never a status).")
    parser.add_argument("task_dir", help="Path to the task directory")
    parser.add_argument("transition", help='Step string e.g. "IMPLEMENTING → REVIEW"')
    args = parser.parse_args()
    if not Path(args.task_dir).is_dir():
        parser.error(f"not a task directory: {args.task_dir}")
    found = [forged_transition(args.transition)] + [
        f"{name}: {why}" for name in ("CREW_WORKFLOW", "CREW_MEMBER") for why in [forged_transition(os.environ.get(name, ""), env=True)] if why
    ]
    refused = next((why for why in found if why), "")
    if refused:
        print(f"log-progress: refused: {refused}; nothing written", file=sys.stderr)
        return 2
    try:
        append_transition(Path(args.task_dir), args.transition)
    except FileNotFoundError as error:
        print(f"log-progress: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
