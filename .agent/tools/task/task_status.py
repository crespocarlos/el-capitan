#!/usr/bin/env python3
"""Single implementation of the SPEC.md `## Status` contract.

Usage: task_status.py <SPEC.md>       print the status value (empty when unset)
       task_status.py --head <SPEC.md> print the normalized state token

Also imported by `crew-ls.py` and `resolve-task-dir.py` so the two can never disagree.

The contract: the value is the first line after a column-0 `## Status` heading, it never
starts with `#`, and an absent or blank value is "unset" (printed as an empty line). The token is
canonical uppercase: `done`, `Done`, and `DONE` are one state, not three, because the store held
both spellings and every query that expected the contract's token saw half the finished work.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

STATUS = re.compile(r"^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$", re.M)
STATES = ("DRAFTING", "APPROVED", "IMPLEMENTING", "ON-HOLD", "DONE")
# A user-only side state from the orchestrator rules: it is not a transition, but it is a value the
# store legitimately holds, so a rewrite reports it rather than rejecting the task outright.
SIDE_STATES = ("ABANDONED",)
ACCEPTED = STATES + SIDE_STATES


class StatusError(ValueError):
    """A status value outside the contract; the message names every allowed token."""


def read_status(path: Path | str) -> str | None:
    """Return the status value, "" when unset, or None when the file is unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    match = STATUS.search(text)
    return match.group(2).strip() if match else ""


def head(value: str | None) -> str:
    """Normalized state token: `IMPLEMENTING`, `ON-HOLD`, `DONE`, or "".

    Trailing punctuation is not part of the state: a status written as a sentence (`DONE.`) and one
    written as a label are the same value, and a query that compared the raw text missed it.
    """
    return value.split()[0].upper().rstrip("(:.,;") if value else ""


def token(value: str | None) -> str:
    """The contract token of a status value, raising `StatusError` for anything unknown.

    The reader stays lenient — a listing must render a malformed task instead of dying on it — but
    a value that becomes authoritative is checked, so a typo fails where it is written rather than
    silently matching no transition rule.
    """
    candidate = head(value)
    if candidate and candidate not in ACCEPTED:
        raise StatusError(f"status {value.strip()!r} is not one of {', '.join(ACCEPTED)}")
    return candidate


def canonical(value: str | None) -> str:
    """The value with its token in the one allowed spelling and any suffix kept verbatim."""
    stripped = (value or "").strip()
    if not stripped:
        return ""
    word, _, rest = stripped.partition(" ")
    token(value)
    return word.upper().rstrip("(:.,;") + (f" {rest}" if rest else "")


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
