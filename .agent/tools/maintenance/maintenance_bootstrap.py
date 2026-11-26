"""Make `.agent/tools` and its package directories importable, found from this file's real path.

An entry point runs through a symlink in `~/.agent/bin` from any cwd; Python puts the resolved
script directory first on `sys.path`, so `import <package>_bootstrap` finds this file. Every package
has a byte-identical copy (crew-lint `bootstrap-identical`); see "Imports" in `.agent/tools/AGENTS.md`.
It runs before any other import, so it depends on nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
PACKAGES = ("task", "review", "memory", "evals", "maintenance")

for _entry in (TOOLS, *(TOOLS / name for name in PACKAGES)):
    if str(_entry) not in sys.path:
        sys.path.insert(1, str(_entry))
