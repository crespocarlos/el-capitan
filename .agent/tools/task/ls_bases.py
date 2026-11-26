"""`landing_bases`: the branches a repository treats as a normal place for work to land.

By default the default branch is the only one, so a PR merged into a parent branch is `landed: no`.
A repo with release branches (`8.x`, `9.1`: backports) says so in its `AGENTS.md`, in either form:

    landing_bases: ^\\d+\\.\\d+$ ^\\d+\\.x$        one line, patterns separated by spaces

    ```landing_bases                           or a fenced block, one pattern per line
    ^\\d+\\.\\d+$
    ^\\d+\\.x$
    ```

A pattern is a regular expression that must match the WHOLE branch name; one that does not compile is
ignored. `crew open pr` (the stack gate) and `crew ls` (`landed`) read the same setting.
"""
from __future__ import annotations

import re
from pathlib import Path

from lib.git import GitError, toplevel

LINE = re.compile(r"^landing_bases:[ \t]*(.*)$", re.M)
BLOCK = re.compile(r"^```landing_bases[ \t]*\n(.*?)^```", re.M | re.S)


def parse(text: str) -> list[str]:
    """The valid patterns `text` declares, in order."""
    raw = [token.strip("`") for found in LINE.findall(text) for token in found.split()]
    for block in BLOCK.findall(text):
        raw += [line.strip().strip("`") for line in block.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    valid: list[str] = []
    for pattern in raw:
        try:
            re.compile(pattern)
        except re.error:
            continue
        if pattern and pattern not in valid:
            valid.append(pattern)
    return valid


def load(root: Path | None = None) -> list[str]:
    """The patterns in the `AGENTS.md` at the root of the repository around `root` (cwd by default)."""
    try:
        top = toplevel(root)
        return parse((top / "AGENTS.md").read_text(encoding="utf-8", errors="replace"))
    except (GitError, OSError):
        return []


def matches(base: str, patterns: list[str]) -> bool:
    """True when `base` fully matches any pattern."""
    return any(re.fullmatch(pattern, base) for pattern in patterns)
