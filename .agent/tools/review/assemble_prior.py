#!/usr/bin/env python3
"""The prior-review block a persona package carries: what an earlier round already reported.

A second review round re-reads the whole diff and, left alone, re-reports the same defects in new
words: two measured rounds at the same `HEAD` shared zero finding fingerprints and still raised the
same subject twice ("the flaky flag and the flaky_probe reason are explained in two bullets" became
"the flaky rule is stated in the flag bullet and the reason bullet"). Fingerprint matching cannot see
that reworded re-raise; a persona reading the earlier titles can.

The block is evidence, never instruction: it tells the persona what was reported and what the author
then did with it — `fixed` means the code changed, `rejected` means the author disagreed — so a
re-raise needs new evidence the block does not already contain.
"""
from __future__ import annotations

import json
from pathlib import Path

PRIOR_HEADING = "## Already reported in an earlier round"
# One line per finding, so the block stays a few KB against a package measured at 235 KB.
TITLE_MAX = 110


def outcomes(review_dir: Path) -> dict[str, str]:
    """Fingerprint → outcome from the run's own `.outcomes` journal, or {} when none was recorded.

    The journal sits beside the run directories (`<task>/review/outcomes.jsonl`), keyed by
    fingerprint, and is written by `crew review address`. An unrecorded finding is absent rather than
    guessed: "the author said nothing" and "the author fixed it" are different facts for a re-raise.
    """
    path = review_dir.parent / "outcomes.jsonl"
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return {}
    return {row["fingerprint"]: row["outcome"]
            for row in rows if isinstance(row, dict) and row.get("fingerprint") and row.get("outcome")}


def findings(previous_dir: Path) -> list[dict]:
    """The findings an earlier run consolidated, in their recorded order."""
    for name in ("consolidation.json", "candidates.json"):
        try:
            payload = json.loads((previous_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = payload if isinstance(payload, list) else payload.get("findings") or []
        if items:
            return [item for item in items if isinstance(item, dict)]
    return []


def section(previous_dir: Path) -> str:
    """The block for an earlier run, or "" when it recorded no findings to repeat back.

    Every finding is listed whatever its disposition: a `deferred` one is exactly what a reviewer
    needs to see to decide whether it is now in scope, and a `dropped` one explains why the report a
    reader saw was shorter than what the lenses raised.
    """
    rows = findings(previous_dir)
    if not rows:
        return ""
    decisions = outcomes(previous_dir)
    lines = [PRIOR_HEADING, "",
             f"Round `{previous_dir.name}` reported these. Do not raise one again unless the current",
             "tree gives you new evidence, and say what that evidence is. A finding whose author",
             "decision is `fixed` needs a reason the fix did not hold; `rejected` means the author",
             "disagreed, so restate the case only if you can answer their reason.", ""]
    for row in rows:
        label = str(row.get("label") or "?").strip()
        where = f"{row.get('file')}:{row.get('line')}" if row.get("file") else "(no anchor)"
        disposition = str(row.get("disposition") or "").strip()
        decision = decisions.get(str(row.get("fingerprint") or ""), "")
        tags = ", ".join(tag for tag in (disposition, decision) if tag)
        title = " ".join(str(row.get("title") or "").split())[:TITLE_MAX]
        lines.append(f"- [{label}] `{where}` — {title}" + (f" _({tags})_" if tags else ""))
    return "\n".join(lines) + "\n"
