#!/usr/bin/env python3
"""The eval score row: one scored cell, normalized once at the JSON boundary.

`evals_report.rows` builds these from the score documents and `evals_diagnose` reads them for
change attribution, so the shape lives here rather than in either consumer. `evals_report` stays
the rendering module.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalRow:
    """One scored (run, example, repetition, evaluator) cell, as every command reads it.

    The score documents vary by run — `score`, `why`, and `suite` are genuinely absent on some — so
    `None` means "the index had no value", never "zero".
    """

    commit: str
    time: str
    run: str
    exp: str
    exp_full: str
    example: str
    rep: object
    trace: object
    ev: str
    score: object
    why: str
    direction: str
    suite: object

    def to_json(self) -> dict:
        """The row as JSON, in the key order the score normalizer has always produced."""
        return {
            "commit": self.commit,
            "time": self.time,
            "run": self.run,
            "exp": self.exp,
            "exp_full": self.exp_full,
            "example": self.example,
            "rep": self.rep,
            "trace": self.trace,
            "ev": self.ev,
            "score": self.score,
            "why": self.why,
            "direction": self.direction,
            "suite": self.suite,
        }


def to_row(document: dict, prefix: str) -> EvalRow:
    """Normalize one score document; the tolerances live here and nowhere else."""
    experiment = document.get("experiment_name", document["experiment_id"])
    return EvalRow(
        commit=document["metadata"]["git"]["commit_sha"][:8],
        time=document["@timestamp"],
        run=document["experiment_id"],
        exp=experiment.removeprefix(prefix)[:34],
        exp_full=experiment,
        example=document["example"]["id"],
        rep=document["task"].get("repetition_index"),
        trace=document["task"].get("trace_id"),
        ev=document["evaluator"]["name"],
        score=document["evaluator"].get("score"),
        why=(document["evaluator"].get("explanation") or "").replace("\n", " "),
        direction=document["evaluator"].get("direction", "maximize"),
        suite=document.get("metadata", {}).get("suite_id"),
    )
