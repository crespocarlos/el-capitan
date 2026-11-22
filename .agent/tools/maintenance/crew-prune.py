#!/usr/bin/env python3
"""Report catalog commands nothing references, so the next uncalled command is visible.

A prompt change is unmeasurable without a suite; a command surface grows without one, because
nothing notices a command that no prompt, hook, installer, or other tool names. The verdict here is
narrow on purpose: a command with no reference at all is `uncalled`, and that is the only automatic
judgment. Anything the report cannot settle — a command whose only mention is a test — is listed in
its own verdict so a person decides.

Usage: crew-prune.py [--root DIR] [--tasks-dir DIR] [--json]
Exit:  0 when nothing is uncalled, 1 when at least one command is, 2 when the catalog is unreadable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_MAINTENANCE = Path(__file__).resolve().parent
_TOOLS = _MAINTENANCE.parent
for _path in (_TOOLS, _MAINTENANCE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from prune_callers import (  # noqa: E402
    caller_texts,
    count,
    journal_texts,
    telemetry,
    tool_names,
    verdict,
)

WIDTHS = {"name": 30, "verdict": 12, "other": 9}


def defining_files(name: str, corpus: dict) -> set[Path]:
    """The command's own file, which names itself in its usage text and is not a caller."""
    return {path for group in ("tools", "tests") for path, _ in corpus[group] if path.name == name}


def command_row(name: str, corpus: dict, journals: list) -> dict:
    """One command's counts per caller group and the verdict those counts support."""
    own = defining_files(name, corpus)
    counts = {group: sum(1 for path, text in texts if path not in own and name in text)
              for group, texts in corpus.items()}
    row = {"name": name, **counts, "journals": telemetry(name, journals)}
    row["verdict"] = verdict(counts)
    return row


def rows(root: Path, tasks_dir: Path | None) -> list[dict]:
    corpus = caller_texts(root)
    journals = journal_texts(tasks_dir)
    return [command_row(name, corpus, journals) for name in tool_names(root)]


def print_table(results: list[dict]) -> None:
    """One table, then the counts that make the verdict auditable."""
    columns = ("name", "verdict", "prompts", "hooks", "install", "tools", "tests", "journals")
    print("".join(name.upper().ljust(WIDTHS.get(name, WIDTHS["other"])) for name in columns))
    for row in results:
        print("".join(str(row[name]).ljust(WIDTHS.get(name, WIDTHS["other"])) for name in columns))
    uncalled = [row["name"] for row in results if row["verdict"] == "uncalled"]
    test_only = [row["name"] for row in results if row["verdict"] == "test-only"]
    print()
    print(f"{len(results)} commands: {len(results) - len(uncalled) - len(test_only)} called, "
          f"{len(test_only)} named only by a test, {len(uncalled)} uncalled")
    if test_only:
        print(f"test-only (a person decides): {', '.join(test_only)}")
    if uncalled:
        print(f"uncalled (no reference at all): {', '.join(uncalled)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report catalog commands with no caller; uncalled is the only automatic verdict.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3],
                        help="repository root (default: the one this file lives in)")
    parser.add_argument("--tasks-dir", type=Path, default=None,
                        help="task journals to count invocations from; reported, never decisive")
    parser.add_argument("--json", action="store_true",
                        help="print the rows as a JSON array on stdout")
    args = parser.parse_args()
    if not args.root.is_dir():
        print(f"error: root does not exist: {args.root}", file=sys.stderr)
        return 2
    try:
        results = rows(args.root.resolve(), args.tasks_dir)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_table(results)
    return 1 if any(row["verdict"] == "uncalled" for row in results) else 0


if __name__ == "__main__":
    sys.exit(main())
