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
    UNSCORED,
    add,
    band,
    band_name,
    bucket,
    field_gaps,
    finish,
    load,
    review_dirs,
)
from review_outcomes import by_shape, decided, persona_names, scored


def collect(tasks_dir: Path) -> dict:
    """One pass over the corpus: the review list, the findings, and every outcome join."""
    reviews = []
    totals = bucket()
    labels: dict[str, dict] = {}
    personas: dict[str, dict] = {}
    bands: dict[str, dict] = {}
    shapes = {"review": 0, "task": 0}
    findings: list[dict] = []
    for directory in review_dirs(tasks_dir):
        loaded = load(directory)
        outcomes = decided(directory)
        raised = scored(directory)
        counts = by_shape(directory)
        for shape, value in counts.items():
            shapes[shape] += value
        reviews.append({"review": str(directory), "findings": len(loaded),
                        "recorded": len([f for f in loaded
                                         if str(f.get("fingerprint")) in outcomes]),
                        "journals": counts})
        for finding in loaded:
            findings.append(finding)
            key = str(finding.get("fingerprint"))
            outcome = outcomes.get(key, "")
            # The decision's recorded score wins: a raise is only evidence while it stays attached to
            # the read that settled it, so a band is the score the finding was acted on under.
            level = raised.get(key, finding.get("confidence"))
            add(totals, outcome)
            add(labels.setdefault(str(finding.get("label")), bucket()), outcome)
            add(bands.setdefault(band(level), bucket()), outcome)
            for name in persona_names(finding.get("persona")) or ["unattributed"]:
                add(personas.setdefault(name, bucket()), outcome)
    return {"reviews": reviews, "findings": findings, "totals": finish(totals),
            "labels": {name: finish(row) for name, row in sorted(labels.items())},
            "personas": {name: finish(row) for name, row in sorted(personas.items())},
            "confidence": {score: finish(bands[score]) for score in sorted_bands(bands)},
            "journals": shapes, "gaps": field_gaps(findings)}


def sorted_bands(bands: dict[str, dict]) -> list[str]:
    """Bands high to low, with `unscored` last: a legacy count is not a band and never sorts among them."""
    scored = sorted((score for score in bands if score != UNSCORED), key=int, reverse=True)
    return scored + ([UNSCORED] if UNSCORED in bands else [])


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


def fix_rate(row: dict) -> str:
    """The share of a band's decided findings that were fixed, with the base beside it."""
    decided_count = row["fixed"] + row["rejected"]
    if not decided_count:
        return f"no decided findings ({row['findings']} found, {row['unrecorded']} unrecorded)"
    return (f"fix rate {row['fixed'] / decided_count:.2f} over {decided_count} decided "
            f"({row['fixed']} fixed, {row['rejected']} rejected); "
            f"{row['unrecorded']} unrecorded")


def confidence_line(score: str, row: dict) -> str:
    """One confidence band: its name, its count, and its fix rate — or the legacy row, unbanded."""
    if score == UNSCORED:
        return (f"- {UNSCORED}: {row['findings']} findings written before the score existed "
                f"({row['recorded']} with a decision, {row['unrecorded']} unrecorded)")
    return f"- {score} {band_name(score)}: {row['findings']} findings; {fix_rate(row)}"


def render_confidence(payload: dict) -> list[str]:
    """The distribution and the fix rate per band, or the absence of any score at all."""
    bands = payload["confidence"]
    lines = ["", "## Confidence"]
    if not bands:
        return lines + ["- no findings recorded, so there is no distribution to report"]
    lines += [confidence_line(score, row) for score, row in bands.items()]
    if set(bands) == {UNSCORED}:
        lines.append("- every finding predates the score, so no band has a fix rate yet; "
                     "the distribution above is an absence, not a zero")
    return lines


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
              f"- confidence: {gaps['confidence']} of {total} findings unscored",
              "", "## Findings by label"]
    lines += [label_line(name, row) for name, row in payload["labels"].items()]
    lines += render_confidence(payload)
    lines += ["", "## Precision by persona"]
    lines += [precision_line(name, row) for name, row in payload["personas"].items()]
    if not totals["recorded"]:
        lines += ["", "No outcome was recorded for any finding, so no precision can be computed. "
                  "Every number above is an absence, not a zero."]
    return lines
