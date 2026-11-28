"""`fail`: a command that cannot proceed prints why on stderr and exits 2 (`EXIT_INVALID`).

Every command imports it. crew-lint `no-systemexit-str` bans
`raise SystemExit("message")` (exit 1); other codes are listed in `src/crew/AGENTS.md`.
"""

from __future__ import annotations

import sys
from typing import NoReturn

EXIT_INVALID = 2


def fail(message: str, code: int = EXIT_INVALID) -> NoReturn:
    """Print `message` to stderr and exit `code` (2: invalid invocation or unavailable infrastructure)."""
    print(message, file=sys.stderr)
    raise SystemExit(code)
