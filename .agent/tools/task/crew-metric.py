#!/usr/bin/env python3
"""crew-metric.py — append an audit-only METRIC line to PROGRESS.md.

Usage: crew-metric.py <TASK_DIR> <payload...> (words joined after "METRIC:"); state never reads it.
`stage_start stage=<implement|review>` and `stage_end ... tokens_reported=<n|unknown>` are validated
(`task_progress`); `stage_end` prints the stage's cost line, which `crew ls --cost` lists.
"""
import argparse
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_progress import append_metric, cost_line, fields


def main() -> int:
    parser = argparse.ArgumentParser(description="Append METRIC audit line to PROGRESS.md.")
    parser.add_argument("task_dir", help="Path to the task directory")
    parser.add_argument(
        "payload",
        nargs=argparse.REMAINDER,
        help="METRIC payload (joined with spaces).",
    )
    args = parser.parse_args()
    task_dir = Path(args.task_dir)
    payload = " ".join(args.payload or []).strip()
    if not payload:
        print("log-metric: empty payload", file=sys.stderr)
        return 1
    if not task_dir.is_dir():
        print(f"log-metric: task_dir does not exist: {task_dir}", file=sys.stderr)
        return 1
    try:
        append_metric(task_dir, payload)
    except (ValueError, OSError) as problem:
        print(f"log-metric: {problem}", file=sys.stderr)
        return 1
    if payload.split()[0] == "stage_end":
        print(cost_line(fields(payload.split())))
    return 0


if __name__ == "__main__":
    sys.exit(main())

