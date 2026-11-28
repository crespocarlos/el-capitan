"""Formats written before Phase 5a still read: `key=value` METRIC lines, a REPORT.md without a Report data block,
and an `assemble.json` without `pending`. Each test feeds the old form to every reader of it and compares with the
new form, so an in-flight task keeps its cost history, its builder's claims and its review gate across the upgrade."""
from __future__ import annotations

import json
from pathlib import Path

from crew.core.review.assemble_inputs import check_inputs
from crew.core.review.review_dispatch_stats import run_entries
from crew.core.task.ls_report import review_runs, stage_pairs
from crew.core.task.task_cost import task_summary
from crew.core.task.task_progress import agent_ends, has_metric, read_entries, stage_usage
from crew.core.task.task_verify_report import unverified_claims

LINES = [
    ("2026-11-20T10:00:00Z", "stage_start stage=review"),
    ("2026-11-20T10:10:00Z", "agent_end agent=reviewer-adversarial agent_id=a1 tokens=9000 input=1000 output=2000 cache_read=3000 cache_write=4000"),
    ("2026-11-20T10:20:00Z", "review run=r1 bytes_in=500 bytes_out=200"),
    ("2026-11-20T10:30:00Z", "stage_end stage=review personas=1 tokens_reported=9000"),
]


def progress(task: Path, old: bool) -> Path:
    """PROGRESS.md with LINES as `key=value` (old) or as the JSON `append_metric` writes (new)."""
    def body(text: str) -> str:
        event, *pairs = text.split()
        fields = dict(pair.split("=", 1) for pair in pairs)
        return json.dumps({"schema_version": 1, "event": event, **{k: int(v) if v.isdigit() else v for k, v in fields.items()}})

    task.mkdir(parents=True)
    (task / "PROGRESS.md").write_text("".join(f"[{at}] METRIC: {text if old else body(text)}\n" for at, text in LINES), encoding="utf-8")
    return task


def readings(task: Path) -> tuple:
    entries = read_entries(task)
    ends = [given for _, given in agent_ends(entries)]
    pairs = [{k: v for k, v in run.items() if k != "at"} for run in stage_pairs(entries)[0]]
    line, lenses = run_entries(task, "r1")
    return (stage_usage(entries), ends, pairs, review_runs(entries, entries[0].at), line, [given for _, given in lenses],
            has_metric(task, "review", run="r1"), task_summary(task))


def test_old_metric_lines_read_as_the_json_ones_in_every_reader(tmp: Path) -> None:
    old, new = readings(progress(tmp / "old", True)), readings(progress(tmp / "new", False))
    assert old == new, (old, new)
    assert old[6] and "review: 1 personas, new 7k" in old[7], old  # the review line is found and the cost line counts the agent


def test_a_report_without_report_data_keeps_its_claims(tmp: Path) -> None:
    old = "## Implementation Report\n\n### Unverified claims\n- `the cache survives a restart` — verify: `pytest -k cache`\n- none\n"
    data = {"schema_version": 1, "unverified_claims": [{"claim": "the cache survives a restart", "verify": "pytest -k cache"}]}
    new = f"## Implementation Report\n\n### Report data\n```json\n{json.dumps(data)}\n```\n"
    assert unverified_claims(old) == unverified_claims(new) == [("the cache survives a restart", "pytest -k cache")]


def test_an_assemble_json_without_pending_still_refuses_its_placeholders(tmp: Path) -> None:
    for name in ("package.diff", "hunks.index.md"):
        (tmp / name).write_text("x\n", encoding="utf-8")
    assert "TODO(prepare)" in check_inputs(tmp, {"questions": {"adversarial": ["TODO(prepare)"]}})
    assert check_inputs(tmp, {"questions": {"adversarial": ["Who reads it?"]}}) == ""
