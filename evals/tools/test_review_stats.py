#!/usr/bin/env python3
"""`crew review-stats`: the counts, the empty case, and the denominator every ratio carries.

The measurement this reports is only worth having if it cannot quietly overstate itself. So the two
cases that matter are a corpus with a few decisions — where precision must travel beside the number
of findings that were never recorded — and a corpus with none, where the command must say so rather
than print `0.00`, which reads as a measured zero instead of an absence.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = (Path(__file__).resolve().parents[2] / ".agent" / "tools" / "review"
        / "crew-review-stats.py")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


def review(tasks: Path, name: str, findings: list[dict]) -> Path:
    """One review directory with a persisted finding list."""
    directory = tasks / "task-1" / "review" / name
    directory.mkdir(parents=True)
    (directory / "consolidation.json").write_text(json.dumps({"findings": findings}))
    return directory


def record(directory: Path, fingerprint: str, outcome: str, persona: str, label: str) -> None:
    """Append one outcome to the task-level journal, the shape most runs wrote."""
    journal = directory.parent / "outcomes.jsonl"
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"fingerprint": fingerprint, "outcome": outcome,
                                 "persona": [persona], "label": label,
                                 "review_dir": str(directory)}) + "\n")


def test_three_outcomes_are_counted_with_their_denominator(tmp: Path) -> None:
    directory = review(tmp, "20261122120000", [
        {"title": "a", "label": "attention", "persona": ["adversarial"], "fingerprint": "a1"},
        {"title": "b", "label": "attention", "persona": ["adversarial"], "fingerprint": "b2"},
        {"title": "c", "label": "nit", "persona": ["code-quality"], "fingerprint": "c3"},
        {"title": "d", "label": "nit", "persona": ["code-quality"], "fingerprint": "d4"},
    ])
    record(directory, "a1", "fixed", "adversarial", "attention")
    record(directory, "b2", "rejected", "adversarial", "attention")
    record(directory, "c3", "fixed", "code-quality", "nit")
    result = run("--tasks-dir", str(tmp), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["totals"]["findings"] == 4, payload["totals"]
    assert payload["totals"]["recorded"] == 3, payload["totals"]
    assert payload["totals"]["unrecorded"] == 1, "a finding with no record is counted, not dropped"
    assert payload["totals"]["precision"] == 0.667, payload["totals"]
    adversarial = payload["personas"]["adversarial"]
    assert adversarial == {"findings": 2, "recorded": 2, "fixed": 1, "rejected": 1,
                           "deferred": 0, "skipped": 0, "unrecorded": 0,
                           "precision": 0.5}, adversarial
    assert payload["labels"]["nit"]["unrecorded"] == 1, payload["labels"]
    # The human table states the same denominator, so a reader of either form sees it.
    table = run("--tasks-dir", str(tmp))
    assert "precision 0.50 over 2 decided" in table.stdout, table.stdout
    assert "precision 1.00 over 1 decided" in table.stdout, "labels report precision too"
    assert "1 unrecorded" in table.stdout, table.stdout


def test_a_corpus_with_no_outcomes_says_so(tmp: Path) -> None:
    """`0.00` over nothing is an absence, and the empty message must distinguish it."""
    review(tmp, "20261122120000", [
        {"title": "a", "label": "attention", "persona": ["adversarial"], "fingerprint": "a1"},
    ])
    result = run("--tasks-dir", str(tmp))
    assert result.returncode == 0, result.stderr
    assert "No outcome was recorded" in result.stdout, result.stdout
    payload = json.loads(run("--tasks-dir", str(tmp), "--json").stdout)
    assert payload["totals"]["recorded"] == 0 and payload["totals"]["precision"] is None, payload


def test_missing_fields_are_counted_against_the_whole_corpus(tmp: Path) -> None:
    """A field missing on a legacy finding is a gap, not an excluded row."""
    review(tmp, "20261122120000", [
        {"title": "a", "label": "attention", "fingerprint": "a1"},
        {"title": "b", "label": "attention", "fingerprint": "b2", "kind": "correctness",
         "hunks": ["h1"], "evidence": "a.ts:3", "verified": True, "validation": "read it"},
    ])
    payload = json.loads(run("--tasks-dir", str(tmp), "--json").stdout)
    assert payload["gaps"]["kind"] == 1, payload["gaps"]
    assert payload["gaps"]["hunks"] == 1, payload["gaps"]
    assert payload["gaps"]["verified"] == 1 and payload["gaps"]["validation"] == 0, payload["gaps"]


def test_the_review_list_honours_limit_and_marks_the_cut(tmp: Path) -> None:
    for index in range(3):
        review(tmp, f"2026112212000{index}", [
            {"title": "a", "label": "nit", "fingerprint": f"f{index}"}])
    result = run("--tasks-dir", str(tmp), "--json", "--limit", "1")
    payload = json.loads(result.stdout)
    assert payload["truncated"] is True and payload["reviewsTotal"] == 3, payload
    assert len(payload["reviews"]) == 1 and "--limit" in payload["hint"], payload


def test_an_unusable_tasks_dir_is_an_error_not_an_empty_report(tmp: Path) -> None:
    """Exit 2 with a reason: a report of zero findings is not the same as a failed read."""
    result = run("--tasks-dir", str(tmp / "missing"))
    assert result.returncode == 2 and "not a directory" in result.stderr, result.stderr


def test_review_local_journal_is_read_too(tmp: Path) -> None:
    """`--review-dir .` journals beside the review; a reader that skipped it lost 15 decisions."""
    directory = review(tmp, "20261122120000", [
        {"title": "a", "label": "attention", "persona": ["adversarial"], "fingerprint": "a1"}])
    (directory / "outcomes.jsonl").write_text(json.dumps({
        "fingerprint": "a1", "outcome": "fixed", "persona": ["adversarial"],
        "label": "attention", "review_dir": "."}) + "\n")
    payload = json.loads(run("--tasks-dir", str(tmp), "--json").stdout)
    assert payload["totals"]["recorded"] == 1, payload["totals"]
    assert payload["journals"] == {"review": 1, "task": 0}, payload["journals"]


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
