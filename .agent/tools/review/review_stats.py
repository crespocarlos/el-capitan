#!/usr/bin/env python3
"""The `crew review-stats` aggregation: findings by label, field gaps, and precision with its base.

Two decisions shape the output. Every ratio carries `unrecorded` beside it, so a precision computed
over the handful of labelled outcomes is never read as a property of the reviewer. And the corpus is
reported as one population — the findings that predate a field are counted as gaps, not excluded —
because excluding them would make the measurement describe a subset nobody recorded.
"""
from __future__ import annotations

from pathlib import Path

from review_corpus import (
    DECIDED,
    add,
    bucket,
    field_gaps,
    finish,
    load,
    review_dirs,
)
from review_outcomes import by_shape, decided, persona_names


def collect(tasks_dir: Path) -> dict:
    """One pass over the corpus: the review list, the findings, and both outcome joins."""
    reviews = []
    totals = bucket()
    labels: dict[str, dict] = {}
    personas: dict[str, dict] = {}
    shapes = {"review": 0, "task": 0}
    findings: list[dict] = []
    for directory in review_dirs(tasks_dir):
        loaded = load(directory)
        outcomes = decided(directory)
        counts = by_shape(directory)
        for shape, value in counts.items():
            shapes[shape] += value
        reviews.append({"review": str(directory), "findings": len(loaded),
                        "recorded": len([f for f in loaded
                                         if str(f.get("fingerprint")) in outcomes]),
                        "journals": counts})
        for finding in loaded:
            findings.append(finding)
            outcome = outcomes.get(str(finding.get("fingerprint")), "")
            add(totals, outcome)
            add(labels.setdefault(str(finding.get("label")), bucket()), outcome)
            for name in persona_names(finding.get("persona")) or ["unattributed"]:
                add(personas.setdefault(name, bucket()), outcome)
    return {"reviews": reviews, "findings": findings, "totals": finish(totals),
            "labels": {name: finish(row) for name, row in sorted(labels.items())},
            "personas": {name: finish(row) for name, row in sorted(personas.items())},
            "journals": shapes, "gaps": field_gaps(findings)}


def undecided(row: dict) -> int:
    """Findings that were recorded but decided no fix either way — deferred, skipped, nothing."""
    return row["recorded"] - row["fixed"] - row["rejected"]


def precision_line(name: str, row: dict) -> str:
    """One persona row: the ratio, its base, and the count that makes the base honest."""
    ratio = "n/a" if row["precision"] is None else f"{row['precision']:.2f}"
    decided_count = row["fixed"] + row["rejected"]
    return (f"- {name}: precision {ratio} over {decided_count} decided "
            f"({row['fixed']} fixed, {row['rejected']} rejected); "
            f"{row['unrecorded']} unrecorded, {undecided(row)} recorded but not a fix")


def label_line(name: str, row: dict) -> str:
    """One label row: how many findings carried it and how many of them were decided."""
    decided_count = row["fixed"] + row["rejected"]
    ratio = "n/a" if row["precision"] is None else f"{row['precision']:.2f}"
    return (f"- {name}: {row['findings']} findings, precision {ratio} over "
            f"{decided_count} decided; {row['unrecorded']} unrecorded")


def gap_line(name: str, count: int, total: int) -> str:
    """One missing-field line: the count, the population, and the share it is missing from."""
    share = f"{count * 100 // total}%" if total else "n/a"
    return f"- {name}: {count} of {total} missing ({share})"


def render(payload: dict) -> list[str]:
    """The human table: the population, where it is thin, and precision guarded by its denominator."""
    totals, gaps, reviews = payload["totals"], payload["gaps"], payload["reviews"]
    shapes, total = payload["journals"], totals["findings"]
    lines = [f"# Review corpus: {len(reviews)} reviews, {total} findings", "",
             "## Outcomes",
             f"- recorded: {totals['recorded']} of {total} "
             f"({totals['fixed']} fixed, {totals['rejected']} rejected, "
             f"{totals['deferred']} deferred, {totals['skipped']} skipped)",
             f"- journals: {shapes['task']} from the task-level journal, "
             f"{shapes['review']} from a review-local one",
             f"- unrecorded: {totals['unrecorded']} of {total} — no decision was ever written",
             "- corpus precision: " + ("n/a" if totals["precision"] is None else
                                       f"{totals['precision']:.2f} over "
                                       f"{totals['fixed'] + totals['rejected']} decided findings"),
             "", "## Missing fields"]
    lines += [gap_line("kind", gaps["kind"], total),
              gap_line("hunks", gaps["hunks"], total),
              gap_line("evidence", gaps["evidence"], total),
              f"- validation: {gaps['validation']} of {gaps['verified']} verified findings",
              "", "## Findings by label"]
    lines += [label_line(name, row) for name, row in payload["labels"].items()]
    lines += ["", "## Precision by persona"]
    lines += [precision_line(name, row) for name, row in payload["personas"].items()]
    if not totals["recorded"]:
        lines += ["", "No outcome was recorded for any finding, so no precision can be computed. "
                  "Every number above is an absence, not a zero."]
    return lines
