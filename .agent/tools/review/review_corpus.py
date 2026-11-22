#!/usr/bin/env python3
"""Aggregating the recorded review corpus into the measurements a reviewer change is judged on.

This module answers one question — what did the reviewers actually produce, and how much of it can
be checked — from the artifacts already on disk. It reads `consolidation.json` for the findings and
the outcome journals for the decisions, and it never infers a decision: a finding with no record is
`unrecorded`, stated as such rather than dropped from the denominator.

Precision is `fixed / (fixed + rejected)` per persona, and it always travels with the unrecorded
count, because a ratio computed over a small recorded slice is not a property of the reviewer.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from review_outcomes import decided, persona_names

FINDING_FILE = "consolidation.json"
# The fields a finding needs before a reader can check it. `validation` is counted against the
# findings that claim `verified`, because a sentence is only required where a check was claimed.
REQUIRED_FIELDS = ("kind", "hunks", "evidence")
DECIDED = ("fixed", "rejected")


def review_dirs(tasks_dir: Path) -> list[Path]:
    """Every review directory under the task store that persisted a finding list."""
    pattern = str(tasks_dir / "*" / "review" / "*" / FINDING_FILE)
    return sorted({Path(path).parent for path in glob.glob(pattern)})


def load(review_dir: Path) -> list[dict]:
    """The findings of one review, or an empty list when the file is unreadable."""
    try:
        payload = json.loads((review_dir / FINDING_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    findings = payload.get("findings") if isinstance(payload, dict) else payload
    return [item for item in findings if isinstance(item, dict)] if isinstance(findings, list) else []


def absent(finding: dict, field: str) -> bool:
    """True when a field carries nothing: missing, null, or an empty list."""
    value = finding.get(field)
    return value is None or (isinstance(value, (list, str)) and not value)


def field_gaps(findings: list[dict]) -> dict[str, int]:
    """How many findings lack each required field, plus validation on the verified ones."""
    gaps = {field: sum(1 for finding in findings if absent(finding, field))
            for field in REQUIRED_FIELDS}
    verified = [finding for finding in findings if finding.get("verified") is True]
    gaps["validation"] = sum(1 for finding in verified if absent(finding, "validation"))
    gaps["verified"] = len(verified)
    return gaps


def bucket() -> dict:
    """A fresh counter row: findings seen, decisions recorded, and the outcomes that carry a ratio."""
    return {"findings": 0, "recorded": 0, "fixed": 0, "rejected": 0,
            "deferred": 0, "skipped": 0, "unrecorded": 0}


def add(row: dict, outcome: str) -> None:
    """Fold one finding's outcome into a counter row; `""` means it was never recorded."""
    row["findings"] += 1
    if not outcome:
        row["unrecorded"] += 1
        return
    row["recorded"] += 1
    if outcome in row:
        row[outcome] += 1


def precision(row: dict) -> float | None:
    """`fixed / (fixed + rejected)`, or None when no finding was decided either way."""
    decided_count = row["fixed"] + row["rejected"]
    return round(row["fixed"] / decided_count, 3) if decided_count else None


def finish(row: dict) -> dict:
    """A counter row as reported: the ratio plus the denominator a reader needs beside it."""
    return {**row, "precision": precision(row)}
