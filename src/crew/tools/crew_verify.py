#!/usr/bin/env python3
"""Run the repository's CI as CI runs it, and check a builder report against the result.

    crew-verify.py [--repo R] [--task-dir D] [--list] [--background | --wait JSON] ...   (task_verify.py)
    crew-verify.py report-check REPORT.md [--gates JSON] [--unverified N]               (task_verify_report.py)

An entry point that dispatches; the run itself is the mirror of the base branch's CI `run:` steps.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] == ["report-check"]:
        from crew.core.task.task_verify_report import main as report_check

        return report_check(arguments[1:])
    from crew.core.task.task_verify import main as verify

    return verify(arguments)


if __name__ == "__main__":
    sys.exit(main())
