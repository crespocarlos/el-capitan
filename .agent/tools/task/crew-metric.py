#!/usr/bin/env python3
"""crew-metric.py — append an audit-only METRIC line to PROGRESS.md.

Never read by pipeline state derivation (git/gh + SPEC remain source of truth).
Usage:
  crew-metric.py <TASK_DIR> <payload...>
Payload words are joined with single spaces after the "METRIC:" prefix.

Example:
  crew-metric.py "$TASK_DIR" implement_start mode=inline
  crew-metric.py "$TASK_DIR" implement_complete tasks_passed=8 tasks_failed=0

Stage keys (validated, see task_cost.py): `stage_start stage=<implement|review>` and
`stage_end stage=<implement|review> [workers=<n>|personas=<n>] tokens_reported=<n|unknown>`. A
`stage_end` also prints the one cost line the stage closes with ("implement: 3 workers, 410k tokens");
`crew ls --cost` reads the same lines. Tokens are what the harness reported, `unknown` otherwise.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from task_cost import cost_line, fields, validate  # noqa: E402


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
    problem = validate(payload.split())
    if problem:
        print(f"log-metric: {problem}", file=sys.stderr)
        return 1
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] METRIC: {payload}\n"
    with (task_dir / "PROGRESS.md").open("a", encoding="utf-8") as handle:
        handle.write(line)
    if payload.split()[0] == "stage_end":
        print(cost_line(fields(payload.split())))
    return 0


if __name__ == "__main__":
    sys.exit(main())

