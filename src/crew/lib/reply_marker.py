"""The dispatch marker that ties a subagent's reply to the directory that expects it.

`write_expect` stores a fresh nonce in `<name>.expect` and returns the line a dispatch prompt opens with;
`MARKER` parses that line back out of the prompt. The subagent-stop hook saves a reply only when the
nonce in its marker equals the one `<name>.expect` holds.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

from crew.lib.files import atomic_write

MARKER = re.compile(r"^crew-review-out: (.+) (\S+) ([0-9a-f]{32})[ \t]*$", re.M)


def write_expect(directory: Path, name: str) -> str:
    """Write a fresh nonce to `<directory>/<name>.expect` and return the marker line for the dispatch prompt."""
    if not directory.is_dir():
        raise ValueError(f"no such review directory: {directory}")
    nonce = secrets.token_hex(16)
    atomic_write(directory / f"{name}.expect", nonce + "\n")
    return f"crew-review-out: {directory.resolve()} {name} {nonce}"
