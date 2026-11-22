#!/usr/bin/env python3
"""Outcome records: one appended line per decision, and the denominator that reads it back.

An outcome answers the question precision needs — did the reviewer's finding turn out to be right —
and it is only knowable at the moment `crew review address` applies or rejects the fix. Nothing
recorded it for 704 of 719 measured findings, so the field existed and the corpus never held it.

Two journal shapes exist because the record path follows the directory the caller named:
`<review>/outcomes.jsonl` for `--review-dir .` run from inside the review, and
`<task>/review/outcomes.jsonl` for a run that named `<task>/review/<ts>`, whose parent is the
task-level review directory. Both are read here: resolving only one shape reported 15 outcomes for
a corpus that holds 349.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

JOURNAL = "outcomes.jsonl"


def journals(review_dir: Path) -> list[Path]:
    """Every journal one review directory can own, without duplicates."""
    candidates = [review_dir / JOURNAL, review_dir.parent / JOURNAL]
    return [path for index, path in enumerate(candidates) if path not in candidates[:index]]


def read_journal(path: Path) -> list[dict]:
    """The parseable records of one journal; a damaged line is skipped, never guessed at."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    records: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("fingerprint"), str):
            records.append(record)
    return records


def owner(path: Path, record: dict) -> Path:
    """The review directory a record attributes itself to, resolved.

    `outcome --review-dir .` records the literal `.`, so a relative value is resolved against the
    journal holding it rather than against whoever reads the journal later.
    """
    named = Path(str(record.get("review_dir") or ".")).expanduser()
    return named.resolve() if named.is_absolute() else (path.parent / named).resolve()


def decided(review_dir: Path) -> dict[str, str]:
    """Fingerprint → outcome for one review directory, the last record winning.

    Last wins because append-only position encodes sequence and an outcome can change: a `deferred`
    fix applied in a later pass is `fixed`, and the earlier line is history rather than truth.
    """
    return {fingerprint: outcome for fingerprint, (outcome, _) in _joined(review_dir).items()}


def _joined(review_dir: Path) -> dict[str, tuple[str, str]]:
    """Fingerprint → (outcome, journal shape) for one review directory.

    The shape is retained because the two journals record different populations: a run scoped to a
    review directory journals beside it, while a run naming the review's path journals once per task
    and disambiguates with its `review_dir` field. Reporting only one shape is what made a corpus
    holding 356 recorded decisions read as 15.
    """
    target = review_dir.resolve()
    found: dict[str, tuple[str, str]] = {}
    for path in journals(review_dir):
        shape = "review" if path.parent == review_dir else "task"
        for record in read_journal(path):
            value = str(record.get("outcome") or "").strip().lower()
            if value and owner(path, record) == target:
                found[record["fingerprint"]] = (value, shape)
    return found


def by_shape(review_dir: Path) -> dict[str, int]:
    """How many findings each journal shape accounts for, so a total can be broken down."""
    counts = {"review": 0, "task": 0}
    for _, shape in _joined(review_dir).values():
        counts[shape] += 1
    return counts


def persona_names(value: object) -> list[str]:
    """The persona list a record or finding names, tolerant of the spellings the corpus holds.

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


def summary(review_dir: Path) -> dict:
    """What one review recorded: counts per outcome and the fingerprints behind them."""
    outcomes = decided(review_dir)
    counts: dict[str, int] = {}
    for value in outcomes.values():
        counts[value] = counts.get(value, 0) + 1
    return {"recorded": len(outcomes), "outcomes": dict(sorted(counts.items())),
            "fingerprints": sorted(outcomes)}


def missing(review_dir: Path, acted: list[str]) -> list[str]:
    """The acted fingerprints with no recorded outcome, so a summary can fail instead of claim.

    `acted` is what the run applied or rejected. Nothing else needs an outcome: a nit left alone is
    a decision the run did not make, and demanding one for every finding would block a commit on
    polish nobody classified.
    """
    outcomes = decided(review_dir)
    return [fingerprint for fingerprint in acted if fingerprint not in outcomes]

