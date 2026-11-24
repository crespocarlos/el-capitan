"""Where a task's review lives: its own copy, or the directory `<task>/run.json` records.

A self, changes, spec, or idea review persists `REVIEW.md` beside the task. A PR review persists
outside task state by design — it must not overwrite a task's review of a local tree — so the task
holds only a pointer. The gate that closes a task read the task copy and nothing else, which made
the review of a PR-reviewed task unreadable and left the work finished but unclosed. Both the
verdict and the `Reviewed at:` commit come from the file this module resolves, so they cannot
disagree about which review they are judging.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REVIEWED_AT = re.compile(r"^Reviewed at:\s*([0-9a-f]{7,40})\s*$", re.M)
LOCAL = "REVIEW.md"


def recorded_review_dir(task: Path) -> Path | None:
    """The review directory `run.json` in the task names, when that directory still exists."""
    try:
        record = json.loads((task / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = record.get("review_dir") if isinstance(record, dict) else None
    if not isinstance(value, str) or not value:
        return None
    directory = Path(value)
    return directory if directory.is_dir() else None


def review_file(task: Path) -> Path | None:
    """The review the gates read, or None when this task has no readable review anywhere.

    The task's own copy wins: it is what a person reads beside the spec, and it is the only file a
    `crew review address` rewrites. The recorded directory is the fallback a PR-mode review needs.
    """
    local = task / LOCAL
    if local.is_file():
        return local
    directory = recorded_review_dir(task)
    candidate = directory / LOCAL if directory is not None else None
    return candidate if candidate is not None and candidate.is_file() else None


def reviewed_at(review: Path | None) -> str:
    """The `Reviewed at:` commit in a review's footer, or "" when it carries none.

    Only the footer is read: the lines from the last `> Next:` onward, or the last five non-empty
    lines when the file has no trailer. A finding may quote the line verbatim — the contract requires
    quoting — and a quote anywhere above the footer is not a claim about which tree was reviewed.
    Reading the whole file let such a quote satisfy the gate that proves a review covers HEAD.

    A fixed line count failed open instead: anything appended below the footer pushed the commit out
    of the window, and `task_gates` then treats a missing commit as warning-grade. Starting at the
    trailer keeps an addendum from silently disabling the check.
    """
    if review is None:
        return ""
    lines = [line for line in review.read_text(encoding="utf-8").splitlines() if line.strip()]
    start = next((index for index in range(len(lines) - 1, -1, -1)
                  if lines[index].startswith("> Next:")), max(len(lines) - 5, 0))
    matches = REVIEWED_AT.findall("\n".join(lines[start:]))
    return matches[-1] if matches else ""
