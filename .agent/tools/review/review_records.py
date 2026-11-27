"""Review records: deferred and dropped findings beside the report, and the outcome journal.

Dedupe keys on title and anchor, not the rendered label, so a raised score never appends twice.
`crew review address` appends one outcome per decision to `<review>/outcomes.jsonl` or
`<task>/review/outcomes.jsonl`; `outcomes` reads both shapes back.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import review_bootstrap  # noqa: F401

from review_models import Finding, score_move
from review_render import label_with_score
from review_vocabulary import PERSONAS, canonical_personas
from task_progress import append_metric, has_metric

from lib.clock import utc_date, utc_iso

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
    stamp = utc_date()
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


def total_bytes(review_dir: Path, personas: list[str], suffix: str) -> int:
    """The summed size of every `<persona><suffix>` in the run directory, missing files as zero."""
    return sum((review_dir / f"{persona}{suffix}").stat().st_size
               for persona in personas
               if (review_dir / f"{persona}{suffix}").is_file())


def measured_personas(review_dir: Path) -> list[str]:
    """The personas this run actually wrote a package for, in canonical order.

    Derived from the directory rather than from `--personas`: a persist that names a subset would
    otherwise record one package's bytes as the run's cost, and `shared_prefix=0` for a run whose
    head is in fact shared, which is indistinguishable from a head that diverges at byte 0.

    `explorer` is dispatched by hand and never gets a lens package, so it is excluded — the same
    rule `assemble_inputs.reviewer_personas` applies to the same registry.
    """
    lenses = [persona for persona in PERSONAS if persona != "explorer"]
    return [persona for persona in canonical_personas(lenses, split_commas=False)
            if (review_dir / f"{persona}.in.md").is_file()]


def shared_prefix(review_dir: Path, personas: list[str]) -> int:
    """The longest byte prefix common to every `<persona>.in.md`, or 0 with fewer than two."""
    texts = [(review_dir / f"{persona}.in.md").read_bytes()
             for persona in personas if (review_dir / f"{persona}.in.md").is_file()]
    if len(texts) < 2:
        return 0
    limit = min(len(text) for text in texts)
    index = 0
    while index < limit and all(text[index] == texts[0][index] for text in texts[1:]):
        index += 1
    return index


def cost_line(review_dir: Path, personas: list[str], mapped: bool) -> str:
    """What the run cost, as one METRIC payload, so a later run can be compared with it.

    `run=` carries the review directory's name, which is its timestamp: it is what lets a later
    aggregate tell one review from a re-persist of the same packages.
    """
    return (f"review run={review_dir.name} "
            f"in_bytes={total_bytes(review_dir, personas, '.in.md')} "
            f"out_bytes={total_bytes(review_dir, personas, '.out.md')} "
            f"personas={len(personas)} "
            f"shared_prefix={shared_prefix(review_dir, personas)} "
            f"mapped={1 if mapped else 0}")


def record_cost(owner: Path | None, review_dir: Path, mapped: bool) -> str:
    """Append the cost line through `task_progress.append_metric`; "" when the run has no task directory.

    `owner` is the task directory `persist` already resolved, so the `.task-id`-versus-`SPEC.md`
    question is answered once, and a review that fell back to a temp path still records its cost
    because its owner came from the caller rather than from parent links. `append_metric` is the one
    METRIC writer (`crew-metric.py` calls it too). Nothing here may fail a review that already
    persisted, so a rejected payload or a failed write is reported and swallowed.
    """
    if owner is None or not owner.is_dir():
        return ""
    personas = measured_personas(review_dir)
    if not personas:
        return ""
    payload = cost_line(review_dir, personas, mapped)
    if has_metric(owner, f"review run={review_dir.name} "):
        return payload
    try:
        append_metric(owner, payload)
    except (OSError, ValueError) as error:
        print(f"warning: cost metric not recorded: {error}", file=sys.stderr)
    return payload


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
    fix applied in a later pass is `fixed`, and the earlier line is history rather than truth. The
    task-level journal holds every review of the task, so a record counts only for the review it names.
    """
    target = review_dir.resolve()
    found: dict[str, str] = {}
    for path in journals(review_dir):
        for record in read_journal(path):
            value = str(record.get("outcome") or "").strip().lower()
            if value and owner(path, record) == target:
                found[record["fingerprint"]] = value
    return found


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


def append_outcome(args) -> int:
    """Append one audit record for a decision, carrying the score it was made under."""
    record = {
        "ts": utc_iso(),
        "review_dir": str(args.review_dir),
        "fingerprint": args.fingerprint,
        "persona": canonical_personas(args.persona),
        "label": args.label,
        "outcome": args.outcome,
        "reason": args.reason,
        "memory_ids": args.memory_id,
    }
    record.update(score_move(args))
    target = args.review_dir.parent / JOURNAL
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))
    return 0
