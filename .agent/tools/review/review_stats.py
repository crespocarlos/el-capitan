"""The `crew review-stats` aggregation over the recorded corpus: findings by label, gaps, precision.

Findings come from `consolidation.json`, decisions from the outcome journals; a finding with no
record is `unrecorded`, never inferred or dropped, and travels beside every ratio. Precision is
`fixed / (fixed + rejected)` per persona over one population (older findings count as field gaps).
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from review_records import by_shape, decided, scored
from review_vocabulary import CONFIDENCE

FINDING_FILE = "consolidation.json"
# The fields a finding needs before a reader can check it. `validation` is counted against the
# findings that claim `verified`, because a sentence is only required where a check was claimed.
REQUIRED_FIELDS = ("kind", "hunks", "evidence")
DECIDED = ("fixed", "rejected")
# A finding with no usable band — pre-score history, or a value outside 1-5 — is `unscored`, never
# folded into a band: a zero-filled distribution would read as a measured result when nothing was
# measured.
UNSCORED = "unscored"


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
    gaps["confidence"] = sum(1 for finding in findings if band(finding.get("confidence")) == UNSCORED)
    return gaps


def band(value: object) -> str:
    """The band a stored score falls in, or `unscored` — a value outside 1-5 is not a band."""
    if isinstance(value, bool) or not isinstance(value, int) or value not in CONFIDENCE:
        return UNSCORED
    return str(value)


def band_name(score: str) -> str:
    """The word behind a score, so a report line does not print a bare number."""
    return CONFIDENCE[int(score)] if score != UNSCORED else UNSCORED


def persona_names(value: object) -> list[str]:
    """The persona list a finding names, tolerant of the spellings the recorded corpus holds.

    Stored data is canonical in 97% of findings, so this absorbs the remainder — a comma-joined
    string, a display-cased name, a `Reviewer ` prefix — instead of splitting precision into
    one-row buckets. It never invents a name: an empty value yields an empty list.
    """
    raw = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in raw:
        for part in str(item or "").split(","):
            name = re.sub(r"\s+", "-", part.strip().lower()).removeprefix("reviewer-")
            if name and name not in names:
                names.append(name)
    return names


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
    """One confidence row: the band, its count, and its fix rate — or the unbanded history row."""
    if score == UNSCORED:
        return (f"- {UNSCORED}: {row['findings']} findings with no usable band — pre-score history, "
                f"or a value outside 1-5 ({row['recorded']} with a decision, "
                f"{row['unrecorded']} unrecorded)")
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
