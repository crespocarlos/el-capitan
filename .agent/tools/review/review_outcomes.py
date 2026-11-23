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
from datetime import datetime, timezone
from pathlib import Path

from review_vocabulary import canonical_personas, confidence_value

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


def scored(directory) -> dict:
    """Fingerprint → the score a decision was made under, when the record carries one.

    A raise is only evidence while it stays attached to the read that settled it, so the outcome
    journal is where the final score is authoritative: `crew review-stats` joins the score the
    finding was acted on under, not the one it arrived with. Absent means the decision recorded no
    score, which stays `unscored` rather than inheriting a persona's original guess.
    """
    found: dict = {}
    for path in journals(directory):
        for record in read_journal(path):
            value = record.get("confidence")
            if isinstance(value, int) and not isinstance(value, bool):
                found[str(record["fingerprint"])] = value
    return found


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


def append(args) -> int:
    """Append one audit record for a decision, carrying the score it was made under.

    A raised score travels with the decision that raised it: `--confidence` is the score the finding
    was acted on under and `--confidence-from` the one it arrived with, so the join in
    `crew review-stats` reads evidence rather than the label the record happens to carry. One without
    the other is refused, for the same reason a raise in `review_gates` needs both halves.
    """
    if (args.confidence is None) != (args.confidence_from is None):
        raise ValueError("--confidence and --confidence-from go together: a raise records both halves")
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "review_dir": str(args.review_dir),
        "fingerprint": args.fingerprint,
        "persona": canonical_personas(args.persona),
        "label": args.label,
        "outcome": args.outcome,
        "reason": args.reason,
        "memory_ids": args.memory_id,
    }
    if args.confidence is not None:
        record["confidence"] = confidence_value(args.confidence)
        record["confidence_from"] = confidence_value(args.confidence_from)
        if args.confidence < args.confidence_from:
            raise ValueError(
                f"--confidence {args.confidence} is below --confidence-from {args.confidence_from}; "
                "a raise only ever moves up"
            )
    target = args.review_dir.parent / JOURNAL
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))
    return 0

