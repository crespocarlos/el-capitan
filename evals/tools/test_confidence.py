#!/usr/bin/env python3
"""The per-finding confidence score: the field, its scale, its floor, its render, and its outcome record.

Confidence was removed once on the reasoning that nothing gated on it, which was wrong in one way:
it was ungated but read. The form removed could not be measured either — one percentage per review,
joinable to nothing. This suite pins the replacement: a 1-5 score per finding with named bands, a
floor for anything the review asks the author to act on, a report line that carries the number, and
an outcome record that keeps the score a decision was made under.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "review" / "crew-review-findings.py"

BANDS = {5: "confirmed", 4: "strong", 3: "likely", 2: "uncertain", 1: "suspicion"}


def run(*args: str) -> subprocess.CompletedProcess:
    return cli(TOOL, *args)


def base(**overrides: object) -> dict:
    """A complete `attention` finding at confidence 4; overrides replace or drop a field."""
    finding = {"title": "Guard missing", "label": "attention", "file": "a.ts", "line": 3,
               "disposition": "patch", "verified": True, "evidence": "a.ts:3",
               "kind": "correctness", "confidence": 4,
               "validation": "read a.ts:1-9; the guard is absent"}
    for key, value in overrides.items():
        if value is None:
            finding.pop(key, None)
        else:
            finding[key] = value
    return finding


def normalize(tmp: Path, payload: list[dict], *flags: str) -> subprocess.CompletedProcess:
    source = tmp / "candidates.json"
    source.write_text(json.dumps(payload))
    return run("normalize", str(source), *flags)


def review_dir(tmp: Path) -> Path:
    """A review directory that already satisfies the persona gate."""
    directory = tmp / "task" / "review" / "ts"
    directory.mkdir(parents=True)
    (directory / "adversarial.in.md").write_text("in")
    (directory / "adversarial.out.md").write_text("### Findings: none\n")
    return directory


def persist(tmp: Path, payload: list[dict], report_text: str = "## Verdict: PASS\n", *flags: str):
    directory = review_dir(tmp) if not (tmp / "task" / "review" / "ts").exists() else (
        tmp / "task" / "review" / "ts")
    (tmp / "report.md").write_text(report_text)
    findings = tmp / "findings.json"
    findings.write_text(json.dumps(payload))
    return run("persist", "--review-dir", str(directory), "--report", str(tmp / "report.md"),
               "--findings", str(findings), "--mode", "changes", "--files", "a.ts",
               "--personas", "adversarial", *flags)


# --- the field and its gate -------------------------------------------------


def test_a_finding_with_no_confidence_is_rejected_naming_every_band(tmp: Path) -> None:
    """Absence is refused at persist, and the message is the remedy: every band, with its anchor."""
    result = persist(tmp, [base(confidence=None)], "## Verdict: PASS\n")
    assert result.returncode == 2, result.stdout
    assert "has no confidence" in result.stderr, result.stderr
    for score, name in BANDS.items():
        assert f"{score} {name}" in result.stderr, f"the rejection must name {score} {name}: {result.stderr}"
    assert not (tmp / "task" / "REVIEW.md").exists(), "a rejected run writes no report"


# (case, finding, flags, exit code, texts stderr must carry): the `normalize` gate on the score.
NORMALIZE = [
    ("a missing score is refused", base(confidence=None), (), 2, ("has no confidence",)),
    *[(f"confidence {bad!r} is outside the scale", base(confidence=bad), (), 2,
       ("invalid confidence", "integer 1-5")) for bad in (0, 6, "high", 4.5, True, "4", [4])],
    *[(f"{label} at {score} belongs as needs more info", base(label=label, confidence=score), (), 2,
       ("below 3", "needs more info")) for label in ("attention", "blocking") for score in (1, 2)],
    ("a question may carry doubt", base(label="needs more info", confidence=1), (), 0, ()),
    ("a nit may carry doubt", base(label="nit", confidence=1), (), 0, ()),
    ("3 is a request the reviewer stands behind", base(confidence=3), (), 0, ()),
    *[(f"a raise with validation {missing!r} has no read", base(confidence=4, confidence_from=2, validation=missing),
       (), 2, ("records no validation sentence", "from 2 to 4")) for missing in (None, "   ", 7)],
    ("a score only ever moves up", base(confidence=2, confidence_from=4, label="needs more info"), (), 2,
     ("only ever moves up",)),
    ("a pair naming one score is not a raise", base(confidence=4, confidence_from=4), (), 2, ("not a raise",)),
    ("--lenient re-reads an unrecorded raise", base(confidence=4, confidence_from=2, validation=None), ("--lenient",),
     0, ()),
]


@pytest.mark.parametrize("case,finding,flags,code,needles", NORMALIZE, ids=[row[0] for row in NORMALIZE])
def test_the_normalize_score_gate(case: str, finding: dict, flags: tuple[str, ...], code: int,
                                  needles: tuple[str, ...], tmp: Path) -> None:
    result = normalize(tmp, [finding], *flags)
    assert result.returncode == code and all(n in result.stderr for n in needles), result.stdout + result.stderr


def test_every_band_is_accepted_and_survives_to_json(tmp: Path) -> None:
    """The scale is the accepted set: each point round-trips as an integer, not a string.

    A nit is used because the bottom two bands are exactly what the floor refuses on a finding the
    review asks the author to act on, which the floor's own test covers.
    """
    for score in BANDS:
        result = normalize(tmp, [base(label="nit", confidence=score)])
        assert result.returncode == 0, f"{score}: {result.stderr}"
        assert json.loads(result.stdout)["findings"][0]["confidence"] == score


def test_a_historical_finding_with_no_score_is_read_through_lenient(tmp: Path) -> None:
    """The record written before the field existed must stay readable, or no old review can be re-read."""
    lenient = normalize(tmp, [base(confidence=None)], "--lenient")
    assert lenient.returncode == 0, lenient.stderr
    assert "confidence" not in json.loads(lenient.stdout)["findings"][0], (
        "an absent score must not be written back as a value"
    )


def test_the_score_stays_out_of_the_fingerprint(tmp: Path) -> None:
    """Identity is this defect in this file; re-scoring one must not create a second finding."""
    low = json.loads(normalize(tmp, [base(confidence=3)]).stdout)["findings"][0]["fingerprint"]
    high = json.loads(normalize(tmp, [base(confidence=5)]).stdout)["findings"][0]["fingerprint"]
    assert low == high


# --- earning a score back ---------------------------------------------------


def test_a_raise_with_a_recorded_read_is_accepted(tmp: Path) -> None:
    """A low score may be earned back, and the record carries both halves: where it came from, and
    the sentence naming what the read settled. That is the difference between evidence and assertion.
    """
    raised = base(confidence=4, confidence_from=2,
                  validation="read src/a.ts:30-50; the guard is present and shadows the caller's")
    result = normalize(tmp, [raised])
    assert result.returncode == 0, result.stderr
    finding = json.loads(result.stdout)["findings"][0]
    assert finding["confidence"] == 4 and finding["confidence_from"] == 2, finding


def test_a_routed_finding_keeps_its_original_score(tmp: Path) -> None:
    """A 1-2 finding that becomes `[needs more info]` keeps the score it arrived with.

    Routing is not a raise: the read did not settle the unknown, so there is nothing to earn back and
    no `confidence_from` to record. The label changes; the doubt stays visible at its own value.
    """
    routed = {"title": "Retry loop may double-fire", "label": "needs more info", "file": "a.ts",
              "line": 9, "kind": "reliability", "confidence": 2, "disposition": "decide",
              "reason": "whether the guard fires before the retry is unread"}
    listed = ("## Review: changes\n\n1. [needs more info · 2] **`a.ts — line 9`**"
              " — Retry loop may double-fire\n\nprobe: skipped no-runtime: no runner here\n\nVerdict: PASS\n")
    result = persist(tmp, [routed], listed)
    assert result.returncode == 0, result.stderr
    written = (tmp / "task" / "review" / "ts" / "REVIEW.md").read_text()
    assert "[needs more info · 2]" in written, written
    # And the routed finding is not a raise, so it needs no `confidence_from`.
    assert persist(tmp, [routed], listed).returncode == 0
    stored = json.loads(normalize(tmp, [routed]).stdout)["findings"][0]
    assert stored["confidence"] == 2 and "confidence_from" not in stored, stored


def test_an_outcome_refuses_half_a_raise(tmp: Path) -> None:
    """The outcome command refuses half a raise, so a record cannot claim one without the other."""
    partial = run_outcome(review_dir(tmp), "--confidence", "5")
    assert partial.returncode == 2 and "go together" in partial.stderr, partial.stderr


def test_a_raise_logged_as_an_outcome_needs_the_read_that_settled_it(tmp: Path) -> None:
    """The outcome journal records a raise with the same two halves a persisted finding does."""
    directory = review_dir(tmp)
    unevidenced = run_outcome(directory, "--confidence", "4", "--confidence-from", "2")
    assert unevidenced.returncode == 2 and "--validation" in unevidenced.stderr, unevidenced.stderr
    # An unchanged pair is not a move, and the gates refuse it in a finding record too.
    same = run_outcome(directory, "--confidence", "4", "--confidence-from", "4")
    assert same.returncode == 2 and "not a move" in same.stderr, same.stderr
    evidenced = run_outcome(directory, "--confidence", "4", "--confidence-from", "2",
                            "--validation", "read src/a.ts:30-50; the guard shadows the caller's")
    assert evidenced.returncode == 0, evidenced.stderr
    record = json.loads(evidenced.stdout)
    assert record["confidence"] == 4 and record["confidence_from"] == 2, record
    assert "guard shadows" in record["validation"], record


def test_a_duplicate_keeps_the_highest_score_in_either_order(tmp: Path) -> None:
    """Candidate order must not decide whether the run clears the floor gate."""
    low = base(persona="adversarial", confidence=2)
    high = base(persona="code-quality", confidence=5)
    for order in ([low, high], [high, low]):
        result = normalize(tmp, order)
        assert result.returncode == 0, result.stderr
        stored = json.loads(result.stdout)["findings"]
        assert len(stored) == 1, stored
        assert stored[0]["confidence"] == 5, stored
        assert sorted(stored[0]["persona"]) == ["adversarial", "code-quality"], stored


def test_a_deferred_finding_is_not_appended_twice_across_a_score_change(tmp: Path) -> None:
    """Dedupe keys on the title and anchor, so history and a later raise both stay one line."""
    directory = review_dir(tmp)
    # An entry written before the score existed: the old shape must still dedupe a newly scored line.
    (tmp / "task" / "DEFERRED.md").write_text(
        "- [2026-11-01] [attention] Old bug — `a.ts:3` — pre-existing\n")
    deferred = base(title="Old bug", disposition="defer", verified=None, evidence=None,
                    validation=None, confidence=2)
    raised = {**deferred, "confidence": 4, "confidence_from": 2,
              "validation": "read a.ts:1-9; the guard is absent"}
    assert persist(tmp, [raised], "## Review: changes\n").returncode == 0
    lines = (tmp / "task" / "DEFERRED.md").read_text().splitlines()
    assert len(lines) == 1, lines
    assert "[attention · 4]" not in lines[0], "the legacy line is left as written, not rewritten"


def run_outcome(review_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return run("outcome", "--review-dir", str(review_dir), "--fingerprint", "c3",
               "--persona", "adversarial", "--label", "attention", "--outcome", "fixed",
               "--reason", "applied", *extra)



# --- the render -------------------------------------------------------------


def test_the_report_line_carries_the_score_beside_the_label(tmp: Path) -> None:
    """`[attention · 4]`, in the label column, not a sentence further down."""
    for path in (str(TOOL.parent), str(TOOL.parent.parent)):
        if path not in sys.path:
            sys.path.insert(0, path)
    from review_models import Finding
    from review_render import label_with_score, score_suffix
    from review_vocabulary import ABSENT

    scored = Finding(title="Guard missing", label="attention", file="a.ts", line=3, confidence=4)
    assert label_with_score(scored) == "[attention · 4]"
    assert score_suffix(scored) == " · 4"
    # A finding written before the score existed renders without the suffix rather than with a
    # placeholder, because a placeholder claims the reviewer was asked.
    legacy = Finding(title="Rename", label="nit", file="b.ts", line=7, confidence=ABSENT)
    assert label_with_score(legacy) == "[nit]"
    assert score_suffix(legacy) == ""


def test_the_deferred_line_and_the_coverage_table_carry_the_score(tmp: Path) -> None:
    """Every generated list uses one renderer, so none of them can drop the number."""
    directory = review_dir(tmp)
    (directory / "hunks.json").write_text(json.dumps({"files": [], "hunks": [{"id": "h1"}]}))
    (directory / "layers.json").write_text(json.dumps({"layers": [
        {"id": "L1", "explainer": "why", "reviewFocus": "- verify", "hunks": ["h1"]}]}))
    payload = [base(hunks=["h1"], confidence=5),
               base(title="Old bug", label="attention", disposition="defer", confidence=3,
                    verified=None, evidence=None, validation=None, file=None, line=None)]
    listed = ("## Review: changes\n\n1. [attention · 5] **`a.ts:3`** — Guard missing\n")
    result = persist(tmp, payload, listed)
    assert result.returncode == 0, result.stderr
    written = (directory / "REVIEW.md").read_text()
    assert "[attention · 5] Guard missing" in written, written
    deferred = (tmp / "task" / "DEFERRED.md").read_text()
    assert "[attention · 3] Old bug" in deferred, deferred
