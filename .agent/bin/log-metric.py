#!/usr/bin/env python3
"""log-metric.py — append an audit-only METRIC line to PROGRESS.md.

Never read by pipeline state derivation (git/gh + SPEC remain source of truth).
Usage:
  log-metric.py <TASK_DIR> <payload...>
Payload words are joined with single spaces after the "METRIC:" prefix.

Example:
  log-metric.py "$TASK_DIR" implement_start mode=inline
  log-metric.py "$TASK_DIR" implement_complete tasks_passed=8 tasks_failed=0
"""
import argparse
import os
import sys
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Append METRIC audit line to PROGRESS.md.")
    parser.add_argument("task_dir", help="Path to the task directory")
    parser.add_argument(
        "payload",
        nargs=argparse.REMAINDER,
        help="METRIC payload (joined with spaces).",
    )
    args = parser.parse_args()
    task_dir = args.task_dir
    payload = " ".join(args.payload or []).strip()
    if not payload:
        print("log-metric: empty payload", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(task_dir):
        print(f"log-metric: task_dir does not exist: {task_dir}", file=sys.stderr)
        sys.exit(1)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] METRIC: {payload}\n"
    progress_path = os.path.join(task_dir, "PROGRESS.md")
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    main()
