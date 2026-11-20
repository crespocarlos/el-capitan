#!/usr/bin/env python3
"""Deprecated alias: use crew-pr-actions.py instead. Removed one release after the rename."""
import os
import sys
from pathlib import Path

REPLACEMENT = Path(__file__).resolve().with_name("crew-pr-actions.py")

if __name__ == "__main__":
    print(f"warning: pr-review-actions.py is deprecated; use crew-pr-actions.py instead",
          file=sys.stderr)
    if not REPLACEMENT.is_file():
        print(f"error: replacement missing: {REPLACEMENT}", file=sys.stderr)
        sys.exit(2)
    os.execv(sys.executable, [sys.executable, str(REPLACEMENT), *sys.argv[1:]])
