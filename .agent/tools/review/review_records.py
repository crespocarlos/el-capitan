#!/usr/bin/env python3
"""The task-level records a review leaves beside its report: deferred and dropped findings.

`persist` writes both, because a finding cut in consolidation is otherwise invisible: one measured
run dropped three legitimate nits to stay inside the nit budget and left no artifact saying so, so a
reviewer who raised one could not tell it had been seen. `defer` and `dropped` differ in meaning and
land in different files: deferred is "real, not this PR's", dropped is "not worth acting on".

Dedupe keys on the title and its anchor rather than the rendered label, because the label carries
the score and a re-run that raised it would append the same finding twice.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from review_models import Finding
from review_render import label_with_score
from review_vocabulary import PERSONAS, canonical_personas

# The one writer of a METRIC line, resolved through this file's real path: installed modules are
# symlinked from `~/.agent/bin` into the repository, so `resolve()` reaches the sibling package.
METRIC = Path(__file__).resolve().parent.parent / "task" / "crew-metric.py"

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
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    rule `assemble_personas` applies to the same registry.
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
    """Append the cost line through `crew-metric.py`; "" when the run has no task directory.

    `owner` is the task directory `persist` already resolved, so the `.task-id`-versus-`SPEC.md`
    question is answered once, and a review that fell back to a temp path still records its cost
    because its owner came from the caller rather than from parent links.

    `crew-metric.py` stays the only writer of a METRIC line — its own docstring says so, and the
    progress lint fails a hand-appended one — but a hyphenated command cannot be imported, so the
    line reaches it as a subprocess argument. Nothing here may fail a review that already persisted,
    so both a non-zero exit and a failed spawn are reported and swallowed.
    """
    if owner is None or not owner.is_dir():
        return ""
    personas = measured_personas(review_dir)
    if not personas:
        return ""
    payload = cost_line(review_dir, personas, mapped)
    progress = owner / "PROGRESS.md"
    if progress.is_file() and f"METRIC: review run={review_dir.name} " in progress.read_text(
            encoding="utf-8", errors="replace"):
        return payload
    try:
        result = subprocess.run([sys.executable, str(METRIC), str(owner), payload],
                                capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"warning: cost metric not recorded: {error}", file=sys.stderr)
        return payload
    if result.returncode != 0:
        print(f"warning: cost metric not recorded: {result.stderr.strip()}", file=sys.stderr)
    return payload
