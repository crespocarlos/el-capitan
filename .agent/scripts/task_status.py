#!/usr/bin/env python3
"""Single implementation of the SPEC.md `## Status` contract.

Usage: task_status.py <SPEC.md>       print the status value (empty when unset)
       task_status.py --head <SPEC.md> print the normalized state token

Also imported by `crew-ls.py` and `resolve-task-dir.py` so the two can never disagree.

The contract: the value is the first line after a column-0 `## Status` heading, it never
starts with `#`, and an absent or blank value is "unset" (printed as an empty line).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

STATUS = re.compile(r"^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$", re.M)


def read_status(path: Path | str) -> str | None:
    """Return the status value, "" when unset, or None when the file is unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    match = STATUS.search(text)
    return match.group(2).strip() if match else ""


def head(value: str | None) -> str:
    """Normalized state token: `IMPLEMENTING`, `ON-HOLD`, `DONE`, or ""."""
    return value.split()[0].upper().rstrip("(:") if value else ""


def main(argv: list[str]) -> int:
    args = list(argv)
    normalized = False
    if args[:1] == ["--head"]:
        normalized, args = True, args[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__.strip())
        return 0 if args else 2
    value = read_status(args[0])
    if value is None:
        print(f"task_status: cannot read {args[0]}", file=sys.stderr)
        return 2
    print(head(value) if normalized else value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
