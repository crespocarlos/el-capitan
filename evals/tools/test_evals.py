#!/usr/bin/env python3
"""The Kibana evals package's offline logic: score rows, pairing, the sign test and the verdict.

No other suite loads `.agent/tools/evals`, so it has this file. The commands query Elasticsearch and
are not run here; only the pure functions between the query and the printout are.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from cli_runner import load

EVALS = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "evals"
load(EVALS / "evals_bootstrap.py")
report = load(EVALS / "evals_report.py")
diagnose = load(EVALS / "evals_diagnose.py")


def document(experiment: str, example: str, score: object, commit: str = "abcdef0123", repetition: int = 0) -> dict:
    return {"experiment_id": f"run-{commit}", "experiment_name": experiment, "@timestamp": "2026-01-01T00:00:00Z",
            "metadata": {"git": {"commit_sha": commit}}, "example": {"id": example},
            "task": {"repetition_index": repetition}, "evaluator": {"name": "Correctness", "score": score}}


def test_rows_trim_the_shared_prefix_drop_duplicates_and_keep_a_missing_score() -> None:
    rows = report.rows([document("suite: alpha", "e1", 1.0), document("suite: alpha", "e1", 0.0),
                        document("suite: beta", "e2", None)])
    assert [(row.exp, row.example, row.score, row.commit) for row in rows] == [
        ("alpha", "e1", 1.0, "abcdef01"), ("beta", "e2", None, "abcdef01")]
    assert report.common_prefix(["a", "b"]) == "", "no shared readable prefix trims nothing"


def test_pairing_keeps_only_examples_both_commits_scored() -> None:
    rows = report.rows([document("x", example, score, commit) for commit, example, score in (
        ("base0000", "e1", 0.0), ("base0000", "e2", 1.0), ("base0000", "e3", None),
        ("cand0000", "e1", 1.0), ("cand0000", "e3", 1.0), ("cand0000", "e4", 1.0))])
    keys, baseline, candidate = diagnose.paired_rows(rows, "base0000", "cand0000")
    assert keys == [("e1", 0)] and baseline[0].score == 0.0 and candidate[0].score == 1.0


@pytest.mark.parametrize("baseline,candidate,expected", [
    ([0, 0, 0, 0, 0], [1, 1, 1, 1, 1], (0.0625, 5)),
    ([0, 1, 1], [1, 1, 0], (1.0, 2)),
    ([1, 1], [1, 1], (1.0, 0)),
])
def test_the_sign_test_excludes_ties(baseline: list[float], candidate: list[float],
                                     expected: tuple[float, int]) -> None:
    assert diagnose.sign_test_pvalue(baseline, candidate) == expected


@pytest.mark.parametrize("p_value,paired,comparable,delta,direction,verdict", [
    (0.01, 9, False, 0.5, "maximize", "not_comparable"),
    (0.01, 2, True, 0.5, "maximize", "insufficient_evidence"),
    (0.20, 9, True, 0.5, "maximize", "insufficient_evidence"),
    (0.01, 9, True, 0.5, "maximize", "improved"),
    (0.01, 9, True, 0.5, "minimize", "regressed"),
])
def test_the_verdict_needs_comparable_paired_significant_evidence(p_value: float, paired: int, comparable: bool,
                                                                  delta: float, direction: str, verdict: str) -> None:
    assert diagnose.verdict_for(p_value, paired, comparable, delta, direction)[0] == verdict
