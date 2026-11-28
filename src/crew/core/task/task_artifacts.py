#!/usr/bin/env python3
"""Bounded task artifacts: each one's text, cut at its edge when over the budget.

The truncation edge per artifact is the interesting part: append-only logs and reports whose
identity fields are appended last keep their tail, everything else keeps its head.
"""

from __future__ import annotations

import stat
from pathlib import Path

from crew.core.task.task_progress import PROGRESS_FILE

# Third field is the truncation edge for an over-budget artifact: `tail` keeps the newest content
# for append-only logs and for reports whose identity fields are appended last. `REVIEW.md` is the one
# report whose identity block is appended by `persist` *after* the findings, so tail keeps the
# decision — verdict, next step, and reviewed commit — rather than the heading it opens with.
ARTIFACTS = (
    (".task-id", "task_id", "head"),
    ("SPEC.md", "spec", "head"),
    (PROGRESS_FILE, "progress", "tail"),
    ("REPORT.md", "report", "head"),
    ("REVIEW.md", "review", "tail"),
    ("DEFERRED.md", "deferred", "head"),
    ("HANDOFF.md", "handoff", "head"),
)
ARTIFACT_KEYS = {key for _, key, _ in ARTIFACTS}
DEFAULT_MAX_CHARS = 12_000


def artifact_text(path: Path, key: str, max_chars: int) -> str:
    """One artifact: `(absent)`, `(unreadable: why)`, or its content, cut at its edge under a `(TRUNCATED: ...)` line."""
    try:
        info = path.stat()
        content = path.read_text(encoding="utf-8", errors="replace") if stat.S_ISREG(info.st_mode) else None
    except FileNotFoundError:
        content = None
    except OSError as error:
        return f"(unreadable: {error})"
    if content is None:
        return "(absent)"
    if len(content) <= max_chars:
        return content
    tail = next(edge for _, name, edge in ARTIFACTS if name == key) == "tail"
    kept = content[-max_chars:] if tail else content[:max_chars]
    return f"(TRUNCATED: {'last' if tail else 'first'} {max_chars} of {len(content.encode())} bytes)\n{kept}"


def artifact_texts(task_dir: Path, requested: list[str], max_chars: int) -> dict[str, str]:
    """Each requested artifact of the task, in the canonical order."""
    return {key: artifact_text(task_dir / name, key, max_chars) for name, key, _ in ARTIFACTS if key in requested}
