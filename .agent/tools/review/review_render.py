#!/usr/bin/env python3
"""Rendering a finding for a report: the number beside the label, never buried in the prose.

A reader scanning ten findings needs the reviewer's confidence in the same column as the severity,
so the score joins the label — `[attention · 4]` — and never appears as its own sentence. The two
generated lists `persist` writes (the layer coverage table and the deferred file) use the same
helper, so a finding rendered in either place cannot drift from the numbered list above it.
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


def anchored_location(finding: Finding) -> str:
    """`path — line N` when both are known, or whichever half the finding recorded."""
    path, line = finding.text("file"), finding.text("line")
    if path and line:
        return f"{path} — line {line}"
    return path or (f"line {line}" if line else "")


def finding_line(finding: Finding, number: int) -> str:
    """One entry of the numbered report list, with the score in the label column.

    The anchor is bolded only when there is one: an unanchored nit renders as its label and title,
    which is what the finding format asks for rather than an empty code span.
    """
    head = f"{number}. {label_with_score(finding)}"
    where = anchored_location(finding)
    return f"{head} **`{where}`** — {finding.title}" if where else f"{head} — {finding.title}"


def report_lines(findings: list[Finding]) -> list[str]:
    """The numbered list for a set of findings, in the order given."""
    return [finding_line(finding, number) for number, finding in enumerate(findings, 1)]
