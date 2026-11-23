#!/usr/bin/env python3
"""Rendering a finding for a report: the number beside the label, never buried in the prose.

A reader scanning ten findings needs the reviewer's confidence in the same column as the severity,
so the score joins the label — `[attention · 4]` — and never appears as its own sentence. Both
generated lists `persist` writes (the layer coverage table and the deferred file) use the same
helper, so a finding rendered in either place cannot drift from the other.

The numbered list itself is not rendered here: the reviewer model writes it into the report, and its
shape is pinned by the contract and by `test_confidence.py` against a persisted report. A second
renderer for it would be code no path runs.
"""
from __future__ import annotations

from review_models import ABSENT, Finding


def score_suffix(finding: Finding) -> str:
    """` · 4` when the finding carries a score, empty when it was written before the field existed.

    Empty rather than a placeholder: a historical review has no score to show, and printing ` · ?`
    would claim the reviewer was asked and said nothing.
    """
    return "" if finding.confidence is ABSENT else f" · {finding.confidence}"


def label_with_score(finding: Finding) -> str:
    """The label and its score as one bracketed token, which is how every report line carries it."""
    return f"[{finding.label}{score_suffix(finding)}]"
