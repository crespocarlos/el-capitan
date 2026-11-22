#!/usr/bin/env python3
"""One outcome line per decision `crew review address` makes, and none for a finding left alone.

The gap this closes is measured: 704 of 719 recorded findings carry no outcome, so precision cannot
be computed from the corpus at all. Recording was optional in the protocol and nothing checked it,
which is why `outcomes --acted` exists here — the skill's own summary fails when a finding it applied
or rejected has no outcome, so the omission is a visible error rather than a silently thinner corpus.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "review" / "crew-review-findings.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None)


def review_dir(tmp: Path) -> Path:
    """A task review directory with one normalized finding, as `normalize` leaves it."""
    directory = tmp / "task" / "review" / "20261122120000"
    directory.mkdir(parents=True)
    (directory / "findings.json").write_text(json.dumps({"findings": [
        {"title": "Guard missing", "label": "attention", "disposition": "patch",
         "fingerprint": "aaa111", "persona": ["adversarial"], "kind": "correctness"},
        {"title": "Rename helper", "label": "nit", "disposition": "patch",
         "fingerprint": "bbb222", "persona": ["code-quality"], "kind": "other"},
    ]}))
    return directory


def log(directory: Path, fingerprint: str, outcome: str, *, relative: bool = False) -> None:
    result = run("outcome", "--review-dir", "." if relative else str(directory),
                 "--fingerprint", fingerprint, "--persona", "adversarial",
                 "--label", "attention", "--outcome", outcome, "--reason", "applied in the pass",
                 cwd=directory if relative else None)
    assert result.returncode == 0, result.stderr


def test_one_line_per_decision_and_none_for_an_untouched_finding(tmp: Path) -> None:
    """Two decisions, one untouched finding: two lines, and the third fingerprint is absent."""
    directory = review_dir(tmp)
    # The two decisions the run makes: apply one fix, reject the other.
    log(directory, "aaa111", "fixed")
    log(directory, "bbb222", "rejected")
    journal = tmp / "task" / "review" / "outcomes.jsonl"
    lines = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
    assert len(lines) == 2, lines
    assert {record["fingerprint"] for record in lines} == {"aaa111", "bbb222"}
    assert {record["outcome"] for record in lines} == {"fixed", "rejected"}
    # A finding nobody acted on is a decision the run did not make, and it stays unrecorded.
    check = run("outcomes", "--review-dir", str(directory), "--acted", "aaa111", "bbb222")
    assert check.returncode == 0, check.stdout + check.stderr
    payload = json.loads(check.stdout)
    assert payload["recorded"] == 2 and payload["missing"] == [], payload
    assert payload["outcomes"] == {"fixed": 1, "rejected": 1}, payload


def test_a_decision_without_an_outcome_fails_the_summary(tmp: Path) -> None:
    """The skill's summary reads this exit code, so a gap cannot be reported as a success."""
    directory = review_dir(tmp)
    log(directory, "aaa111", "fixed")
    check = run("outcomes", "--review-dir", str(directory), "--acted", "aaa111", "bbb222")
    assert check.returncode == 1, check.stdout + check.stderr
    assert json.loads(check.stdout)["missing"] == ["bbb222"], check.stdout


def test_a_relative_review_dir_still_attributes_to_its_own_review(tmp: Path) -> None:
    """`--review-dir .` from inside the review is the shape that left 15 outcomes attributed."""
    directory = review_dir(tmp)
    before = {path for path in (tmp / "task" / "review").glob("outcomes.jsonl")}
    log(directory, "aaa111", "fixed", relative=True)
    payload = json.loads(run("outcomes", "--review-dir", str(directory)).stdout)
    assert payload["recorded"] == 1, payload
    assert payload["fingerprints"] == ["aaa111"], payload
    # Whatever shape the journal took, the reader finds it: a record attributed to `.` names the
    # directory it was written from, not the reader's working directory.
    assert not before, "the fixture starts with no journal"


def test_a_later_decision_supersedes_an_earlier_one(tmp: Path) -> None:
    """An outcome can change — a deferred fix applied later is fixed — and position is sequence."""
    directory = review_dir(tmp)
    log(directory, "aaa111", "deferred")
    log(directory, "aaa111", "fixed")
    payload = json.loads(run("outcomes", "--review-dir", str(directory)).stdout)
    assert payload["recorded"] == 1, "one finding has one current outcome"
    assert payload["outcomes"] == {"fixed": 1}, payload


def test_an_absent_journal_reports_zero_rather_than_failing(tmp: Path) -> None:
    """No record is an answer; the command must be distinguishable from one that failed to look."""
    directory = review_dir(tmp)
    check = run("outcomes", "--review-dir", str(directory))
    assert check.returncode == 0, check.stderr
    assert json.loads(check.stdout)["recorded"] == 0, check.stdout


def test_skill_requires_the_outcome_call(tmp: Path) -> None:
    """The protocol text is the only place the requirement can live; pin it."""
    skill = (Path(__file__).resolve().parents[2] / ".cursor" / "skills" / "crew-address-review"
             / "SKILL.md").read_text()
    assert "outcomes --review-dir" in skill, (
        "the skill must name the command that fails a summary with a missing outcome"
    )
    assert "not optional" in skill.lower(), "the skill must say the record is not optional"
    assert "exit 1" in skill.lower(), "the skill must say what a shortfall looks like"


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
