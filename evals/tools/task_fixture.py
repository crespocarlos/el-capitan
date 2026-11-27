"""A fixture task's recorded status: what `crew-task.py` would have logged had it moved the spec there.

A task's `## Status` must equal the newest gate-stamped TRANSITION in its PROGRESS.md (DRAFTING when there is none),
or `crew ls` shows it TAMPERED and every gate refuses it. A fixture that writes SPEC.md at another status records it
here: one gate-stamped `TRANSITION` line with no time, first in PROGRESS.md, so the task's activity is unchanged and
no later entry (a BLOCKED line) is ended by it, and PROGRESS.md takes the spec's modification time, so its age is
unchanged too.
"""
from __future__ import annotations

import os
from pathlib import Path


def record_status(task: Path, status: str) -> Path:
    """Put `TRANSITION: (fixture) → <status token> [gate]` first in `task`'s PROGRESS.md; returns `task`."""
    token = status.split()[0].upper().rstrip("(:.,;") if status.strip() else ""
    progress = task / "PROGRESS.md"
    before = progress.read_text(encoding="utf-8") if progress.is_file() else ""
    progress.write_text(f"TRANSITION: (fixture) → {token or 'DRAFTING'} [gate]\n{before}", encoding="utf-8")
    spec = task / "SPEC.md"
    if spec.exists():
        stat = spec.stat()
        os.utime(progress, (stat.st_atime, stat.st_mtime))
    return task
