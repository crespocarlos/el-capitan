"""Make the shared task modules importable from `tui/`: the `.agent/tools` task bootstrap does the rest.

The TUI reads the same rows as `crew ls` (`ls_data`, `ls_report`) from this checkout's tool tree.
"""
from __future__ import annotations

import sys
from pathlib import Path

TASK_TOOLS = Path(__file__).resolve().parents[1] / ".agent" / "tools" / "task"

if str(TASK_TOOLS) not in sys.path:
    sys.path.insert(1, str(TASK_TOOLS))

import task_bootstrap  # noqa: E402, F401
