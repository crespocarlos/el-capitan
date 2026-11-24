#!/usr/bin/env python3
"""The evidence gates are on by default; `--lenient` is the escape, `--strict` a legacy no-op.

Measured over 84 recorded reviews: 464 findings carried `verified: true` with no `validation`, and
`pipeline.md` told every run to pass `--strict`. Nothing enforced the instruction, so the corpus
drifted one run at a time. These cases pin the flip — omitting the flag gets the checked behaviour —
and the two spellings that must keep working: `--lenient` for a deliberate skip, and `--strict`
because a prompt or script written against the old default still passes it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "review" / "crew-review-findings.py"

UNVERIFIED = "records no validation sentence"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


def write_candidate(tmp: Path, **overrides: object) -> Path:
    """One verified attention finding with an anchor; `overrides` drops or changes a field."""
    finding = {"title": "Guard missing", "label": "attention", "file": "a.ts", "line": 3,
               "disposition": "patch", "verified": True, "evidence": "a.ts:3",
               "kind": "correctness", "confidence": 4,
               "validation": "read a.ts:1-9; the guard is absent"}
    for key, value in overrides.items():
        if value is None:
            finding.pop(key, None)
        else:
            finding[key] = value
    source = tmp / "candidates.json"
    source.write_text(json.dumps([finding]))
    return source


def test_normalize_without_a_flag_applies_the_gates(tmp: Path) -> None:
    """The documented invocation is the enforced one: no flag, no exemption."""
    complete = run("normalize", str(write_candidate(tmp)))
    assert complete.returncode == 0, complete.stderr
    result = run("normalize", str(write_candidate(tmp, validation=None)))
    assert result.returncode == 2, f"no flag must reach the gates: {result.stdout}"
    assert UNVERIFIED in result.stderr, result.stderr


def test_lenient_is_the_escape(tmp: Path) -> None:
    """`--lenient` skips the gates, which is how a caller says so on purpose."""
    source = write_candidate(tmp, validation=None)
    assert run("normalize", str(source)).returncode == 2
    relaxed = run("normalize", str(source), "--lenient")
    assert relaxed.returncode == 0, relaxed.stderr
    assert json.loads(relaxed.stdout)["findings"][0]["title"] == "Guard missing"


def test_strict_stays_accepted_as_a_noop_alias(tmp: Path) -> None:
    """One cycle of grace: the old spelling must not fail a script that follows old docs."""
    source = write_candidate(tmp)
    accepted = run("normalize", str(source), "--strict")
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout) == json.loads(run("normalize", str(source)).stdout), (
        "--strict and the default are one behaviour, so the alias cannot drift"
    )
    # It cannot re-enable what --lenient turned off: two spellings of one flag would make the
    # winner depend on argument order.
    assert run("normalize", str(write_candidate(tmp, validation=None)),
               "--lenient", "--strict").returncode == 0


def test_persist_without_a_flag_applies_the_gates(tmp: Path) -> None:
    """`persist` is the other half of the flip; the same finding must fail there unflagged."""
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report = tmp / "report.md"
    # The list and the verdict both mirror the one emitted finding, so the lenient run below fails
    # only if a gate it should skip is still running.
    report.write_text("## Verdict: WARN\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n")
    findings = write_candidate(tmp, validation=None)
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report),
            "--findings", str(findings), "--mode", "changes", "--files", "a.ts",
            "--personas", "adversarial")
    result = run(*args)
    assert result.returncode == 2, f"persist must gate an unflagged call: {result.stdout}"
    assert UNVERIFIED in result.stderr, result.stderr
    assert not (review_dir / "REVIEW.md").exists(), "a gated run writes no report"
    assert run(*args, "--lenient").returncode == 0
    assert (review_dir / "REVIEW.md").is_file()


def test_gates_reach_a_review_that_passes_no_file_list(tmp: Path) -> None:
    """A spec or idea review has no `--files`; the per-finding rules must still run there."""
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report = tmp / "report.md"
    report.write_text("## Review: Spec\n")
    findings = write_candidate(tmp, validation=None)
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                 "--findings", str(findings), "--mode", "spec", "--personas", "adversarial")
    assert result.returncode == 2 and UNVERIFIED in result.stderr, result.stderr
    assert not (tmp / "task" / "REVIEW.spec.md").exists()


def test_kind_is_required_at_persist_and_names_every_value(tmp: Path) -> None:
    """`persist` rejects a finding with no `kind`, and the message lists the whole vocabulary.

    Naming every value is the remedy, not decoration: 713 of 719 measured findings had no `kind`,
    which means the personas that wrote them had not read `KINDS`. A rejection they can act on from
    the message alone is the difference between one round trip and a silently thinner corpus.
    """
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report = tmp / "report.md"
    report.write_text("## Verdict: WARN\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n")
    findings = write_candidate(tmp, kind=None)
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report),
            "--findings", str(findings), "--mode", "changes", "--personas", "adversarial")
    result = run(*args)
    assert result.returncode == 2 and "has no kind" in result.stderr, result.stderr
    for value in ("security", "correctness", "reliability", "documentation", "testing", "other"):
        assert value in result.stderr, f"the rejection must name {value}: {result.stderr}"
    assert not (review_dir / "REVIEW.md").exists(), "a rejected run writes no report"
    assert run(*args, "--lenient").returncode == 0, "a finding written before kind is still readable"


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                test(Path(directory))
                print(f"pass: {test.__name__}")
            except AssertionError as error:
                failed += 1
                print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
