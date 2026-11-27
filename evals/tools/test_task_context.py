#!/usr/bin/env python3
"""Hermetic checks for crew-task-context.py: resolution, subsetting, truncation, rendering."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "task" / "crew-task-context.py"

SPEC = "# Spec: demo\n\n## Status\nAPPROVED\n" + ("body line\n" * 40)
PROGRESS = "".join(f"[2026-11-{day:02d} 10:00] TRANSITION: step {day}\n" for day in range(1, 29))
REVIEW = ("# Review\n\n" + ("finding text here\n" * 60)
          + "\n### Files reviewed\n- `a.py`\n\nVerdict: WARN\n"
            "> Next: run `crew review address` to resolve blocking findings, or `crew commit` when "
            "the verdict is PASS or WARN.\nReviewed at: abcdef1\n")
NOWHERE = ("--remote", "https://example.invalid/none.git", "--branch", "none")


def run(*arguments: str, task_dir: Path | None = None) -> subprocess.CompletedProcess:
    return cli(TOOL, *arguments, env={"CREW_TASK_DIR": str(task_dir) if task_dir else None})


def make_task(store: Path) -> Path:
    task = store / "task"
    task.mkdir()
    (task / ".task-id").write_text(json.dumps({
        "uuid": "TEST", "repo_remote_url": "git@example.invalid:owner/demo.git",
        "branch": "demo", "slug": "demo-task", "created_at": "2026-11-01T00:00:00Z",
    }))
    (task / "SPEC.md").write_text(SPEC)
    (task / "PROGRESS.md").write_text(PROGRESS)
    (task / "REVIEW.md").write_text(REVIEW)
    return task


@pytest.mark.parametrize("arguments", [["--max-chars", "-1"], ["--max-chars", "0"], ["--artifacts", "spec,nope"],
                                       ["--artifacts", " , "]])
def test_invalid_invocations_exit_2(arguments: list[str], tmp: Path) -> None:
    result = run(*arguments, task_dir=make_task(tmp))
    assert result.returncode == 2, result.stdout + result.stderr


def test_the_cached_task_and_its_artifacts(tmp: Path) -> None:
    task = make_task(tmp)
    result = run("--json", task_dir=task)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert (payload["task"]["directory"], payload["task"]["status"]) == (str(task), "APPROVED"), payload["task"]
    assert sorted(payload["artifacts"]) == ["deferred", "handoff", "progress", "report", "review", "spec", "task_id"]
    assert payload["artifacts"]["handoff"]["state"] == "absent"
    # An explicit --task-dir wins over the cache and subsets both renderings identically.
    payload = json.loads(run("--task-dir", str(task), "--artifacts", " spec , review ", "--json").stdout)
    assert sorted(payload["artifacts"]) == ["review", "spec"], sorted(payload["artifacts"])
    assert "PROGRESS.md" not in run("--task-dir", str(task), "--artifacts", "spec,review").stdout
    # A branch override describes another context, so the cached task is not reused.
    assert json.loads(run("--json", *NOWHERE, task_dir=task).stdout)["task"]["found"] is False
    assert run("--task-dir", str(tmp)).returncode == 2, "a non-task directory is an invocation error"


def test_truncation_keeps_the_identity_edge(tmp: Path) -> None:
    """Reports keep the tail (the footer persist appends), specs the head, progress its newest events."""
    task = make_task(tmp)
    payload = json.loads(run("--task-dir", str(task), "--max-chars", "200", "--json").stdout)
    review = payload["artifacts"]["review"]
    assert review["truncated"] is True and review["truncated_edge"] == "tail", review
    for footer_line in ("Verdict: WARN", "> Next: run `crew review address`", "Reviewed at: abcdef1"):
        assert footer_line in review["content"], review["content"][-400:]
    spec = payload["artifacts"]["spec"]
    assert spec["content"].startswith("# Spec: demo") and spec["bytes"] == len(SPEC.encode("utf-8"))
    assert "step 28" in payload["artifacts"]["progress"]["content"]
    assert "TRUNCATED" in run("--task-dir", str(task), "--max-chars", "200", "--artifacts", "review").stdout


def test_no_task_anywhere_reports_every_artifact_absent() -> None:
    result = run("--json", *NOWHERE)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["task"]["found"] is False, payload["task"]
    assert all(entry["state"] == "absent" for entry in payload["artifacts"].values())
