#!/usr/bin/env python3
"""The task-level records a review leaves beside its report: deferred and dropped findings.

`persist` writes both, because a finding cut in consolidation is otherwise invisible: one measured
run dropped three legitimate nits to stay inside the nit budget and left no artifact saying so, so a
reviewer who raised one could not tell it had been seen. `defer` and `dropped` differ in meaning and
land in different files: deferred is "real, not this PR's", dropped is "not worth acting on".

Dedupe keys on the title and its anchor rather than the rendered label, because the label carries
the score and a re-run that raised it would append the same finding twice.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from review_models import Finding
from review_render import label_with_score

# Disposition → the file it is recorded in, and the reason written when the finding states none.
RECORDED = (
    ("DEFERRED.md", "defer", "pre-existing or out of scope"),
    ("DROPPED.md", "dropped", "dropped in consolidation"),
)
RECORDED_DISPOSITIONS = frozenset(disposition for _, disposition, _ in RECORDED)


def identity(finding: Finding) -> str:
    """The dedupe key: the title and its anchor, which survive a score change or a new reason."""
    where = f"{finding.text('file')}:{finding.text('line')}".strip(":")
    return f"{finding.title} — `{where}`"


def line(finding: Finding, stamp: str, default_reason: str) -> str:
    """One record line: when, its label and score, its title, its anchor, and why."""
    reason = finding.text("reason") or default_reason
    return f"- [{stamp}] {label_with_score(finding)} {identity(finding)} — {reason}\n"


def append(owner: Path, rows: list[Finding]) -> dict[str, int]:
    """Append each deferred and dropped finding, skipping one already recorded. Returns the counts."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counts: dict[str, int] = {}
    for filename, disposition, default_reason in RECORDED:
        selected = [f for f in rows if f.disposition == disposition]
        if not selected:
            continue
        path = owner / filename
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        written = 0
        with path.open("a", encoding="utf-8") as handle:
            for finding in selected:
                if identity(finding) in existing:
                    continue
                handle.write(line(finding, stamp, default_reason))
                written += 1
        counts[filename] = written
    return counts
