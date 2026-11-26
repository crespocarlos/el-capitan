#!/usr/bin/env python3
"""Render `report.md` from `consolidation.json`: the numbered list `persist` compares to the findings.

The list is written from the same records `persist` reads, so its label, score and anchor cannot
disagree with them (the failure that cost a retry per hand-built report). Only emitted findings are
numbered. A representative of a group carries one `merged N duplicates` line and each original it
absorbed is listed under it with its own label, so nothing a persona said is hidden. No `Verdict:` line is
written: `persist` derives it (and caps a degraded review) in the footer.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lib.files import atomic_write
from review_findings import read_findings
from review_models import Finding
from review_render import label_with_score


def anchor_text(finding: Finding) -> str:
    """`file:line` as `persist` reads it back: the record's own file and line, else its evidence."""
    if finding.text("file") and finding.text("line").isdigit():
        return f"{finding.text('file')}:{finding.text('line')}"
    return finding.text("evidence")


def originals(findings: list[Finding], representative: Finding) -> list[Finding]:
    """The merged findings whose `merged_into` is the representative's group id (never its title)."""
    group = representative.extra.get("group")
    return [f for f in findings if group and f.disposition == "merged" and f.extra.get("merged_into") == group]


def entry(number: int, finding: Finding, absorbed: list[Finding]) -> list[str]:
    lines = [f"{number}. {label_with_score(finding)} — {finding.title}"]
    if anchor_text(finding):
        lines.append(f"   Anchor: {anchor_text(finding)}")
    if finding.extra.get("anchor") == "non-hunk":
        lines.append("   Outside the diff: read at the reviewed head, not a changed hunk.")
    if finding.extra.get("group_severity"):
        lines.append(f"   Group severity: {finding.extra['group_severity']}")
    if absorbed:
        lines.append(f"   Merged {len(absorbed)} duplicate{'' if len(absorbed) == 1 else 's'}; originals:")
        for other in absorbed:
            who = ", ".join(other.persona) if isinstance(other.persona, list) else "unattributed"
            lines.append(f"   - {label_with_score(other)} {other.title} ({who}; {anchor_text(other) or 'no anchor'})")
    return lines


def render_report(review_dir: Path, mode: str) -> int:
    source = review_dir / "consolidation.json"
    if not source.is_file():
        raise ValueError(f"{source} not found: run `normalize --output` on the draft candidates first")
    findings = read_findings(source)
    emitted = [f for f in findings if f.is_emitted()]
    merged = [f for f in findings if f.disposition == "merged"]
    body = [f"## Review: {mode}", "", f"Consolidated {len(findings)} candidates: {len(emitted)} emitted, "
            f"merged {len(merged)} duplicates." if merged else
            f"Consolidated {len(findings)} candidates: {len(emitted)} emitted, no duplicates merged.", ""]
    for number, finding in enumerate(emitted, 1):
        body.extend(entry(number, finding, originals(findings, finding)))
        body.append("")
    if not emitted:
        body.append("No emitted findings.")
    target = review_dir / "report.md"
    atomic_write(target, "\n".join(body).rstrip() + "\n")
    print(f"report: {target} ({len(emitted)} emitted, merged {len(merged)} duplicates)", file=sys.stdout)
    return 0
