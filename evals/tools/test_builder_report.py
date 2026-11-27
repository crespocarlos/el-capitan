#!/usr/bin/env python3
"""A builder's reply becomes its task's REPORT.md without the builder writing it.

The `SubagentStop` hook saves a `crew-builder` reply whose dispatch prompt opens with `crew-task: <TASK_DIR>`, from
the `## Implementation Report` heading on, beside a provenance record; a report that fails `report-check` is still
saved, with one WARN line in PROGRESS.md. A reply without the heading, or another agent's reply, saves nothing.
`crew-task.py report save` does the same from stdin for a harness without the hook.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
TASK = TOOLS / "task" / "crew-task.py"
HOOK = ROOT / ".claude" / "hooks" / "capture-reply.sh"
GATES = {"schema_version": 1, "gates": [{"name": "test", "exit": 0}]}
REPORT = ("## Implementation Report\n\n**Tasks:** 1/1 passed\n**Harness:** claude-code\n\n### Quality gates\n"
          "test exit=0\n- `test` — pass\n\n### Unverified claims\nnone\n\n### Report data\n```json\n"
          '{"schema_version": 1, "tasks": {"passed": 1, "total": 1}, "gates": [{"name": "test", "exit": 0}]}\n```\n')


def world(tmp: Path) -> tuple[Path, Path]:
    """A HOME with crew-review-findings.py on its bin path and one IMPLEMENTING task with a gates file."""
    home = tmp / "home"
    (home / ".agent" / "bin").mkdir(parents=True)
    (home / ".agent" / "bin" / "crew-review-findings.py").symlink_to(TOOLS / "review" / "crew-review-findings.py")
    task_dir = home / ".agent" / "tasks" / "built"
    task_dir.mkdir(parents=True)
    (task_dir / "SPEC.md").write_text("# Built\n\n## Status\nIMPLEMENTING\n", encoding="utf-8")
    (task_dir / "gates.json").write_text(json.dumps(GATES), encoding="utf-8")
    return home, task_dir


def stop(tmp: Path, home: Path, prompt: str, reply: str, agent: str) -> subprocess.CompletedProcess:
    """One SubagentStop over a transcript whose last assistant message is `reply`."""
    said = {"id": "m1", "role": "assistant", "model": "m-1", "content": [{"type": "text", "text": reply}]}
    turns = [{"type": "user", "message": {"role": "user", "content": prompt}}, {"type": "assistant", "message": said}]
    transcript = tmp / "agent.jsonl"
    transcript.write_text("".join(json.dumps(turn) + "\n" for turn in turns), encoding="utf-8")
    payload = {"hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": agent,
               "agent_transcript_path": str(transcript), "last_assistant_message": "a summary, not the reply"}
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                          env={**os.environ, "HOME": str(home)})


HEAD = "crew-task: {task}\n"
FAILING = REPORT.replace("exit=0", "exit=1")
# (case, agent, the dispatch prompt, the reply, the files that must be saved, a WARN expected, what stdout must say)
CASES = [
    ("a builder reply", "crew-builder", HEAD + "Implement T1.", "Done.\n\n" + REPORT, ["REPORT.md"], False, "saved"),
    ("a batch reply", "crew-builder", "TASK_RANGE: 1-6\n" + HEAD + "\nImplement T1-T6.", REPORT,
     ["REPORT.part-1-6.md"], False, "saved"),
    ("the final batch's reply", "crew-builder", HEAD + "TASK_RANGE: 7-9 final\n\nMerge the parts.", REPORT,
     ["REPORT.md", "REPORT.part-7-9.md"], False, "saved"),
    ("a range quoted below the header", "crew-builder", HEAD + "\nEarlier parts:\nTASK_RANGE: 1-6\n", REPORT,
     ["REPORT.md"], False, "saved"),
    ("two ranges in the header", "crew-builder", HEAD + "TASK_RANGE: 1-6\nTASK_RANGE: 7-9 final\n", REPORT, [],
     False, "no report saved: 2 TASK_RANGE lines"),
    ("a reply that fails report-check", "crew-builder", HEAD + "Implement T1.", FAILING, ["REPORT.md"], True, "saved"),
    ("a reply without the heading", "crew-builder", HEAD + "Implement T1.", "report: done\n", [], False,
     "no report saved: the reply has no"),
    ("a builder prompt with no task line", "crew-builder", "Implement T1.", REPORT, [], False,
     "no report saved: the dispatch prompt has no"),
    ("a non-builder reply", "general-purpose", HEAD + "Implement T1.", REPORT, [], False, ""),
]


@pytest.mark.parametrize("case, agent, prompt, reply, saved, warned, says", CASES, ids=[row[0] for row in CASES])
def test_the_hook_saves_a_builder_report(tmp: Path, case: str, agent: str, prompt: str, reply: str,
                                         saved: list[str], warned: bool, says: str) -> None:
    home, task_dir = world(tmp)
    done = stop(tmp, home, prompt.format(task=task_dir), reply, agent)
    assert done.returncode == 0 and f"capture-reply: {says}" in done.stdout, done
    if not says:  # another agent's run says nothing about a report
        assert "report" not in done.stdout.lower(), done.stdout
    reports = sorted(path.name for path in task_dir.glob("REPORT*.md"))
    progress_file = task_dir / "PROGRESS.md"
    progress = progress_file.read_text(encoding="utf-8") if progress_file.exists() else ""
    assert reports == saved and ("WARN: " + saved[0] + " fails report-check" in progress if warned else
                                 "WARN" not in progress), (reports, progress)
    for name in saved:
        text = (task_dir / name).read_text(encoding="utf-8")
        record = json.loads((task_dir / name.replace(".md", ".provenance.json")).read_text(encoding="utf-8"))
        assert text.startswith("## Implementation Report") and "Done." not in text, text[:80]
        assert (record["harness"], record["agent_id"], record["model"], record["report"]) == \
            ("claude-code", "a1", "m-1", name), record
        assert record["report_check"] == ("fail" if warned else "ok"), record


def test_report_save_reads_the_reply_on_stdin(tmp: Path) -> None:
    """The harness without the hook pipes the reply in; a reply without the heading exits 1 and saves nothing."""
    home, task_dir = world(tmp)
    env = {"HOME": str(home)}
    missing = cli(TASK, "report", "save", str(task_dir), env=env, stdin="report: done\n")
    assert missing.returncode == 1 and not (task_dir / "REPORT.md").exists(), missing
    done = cli(TASK, "report", "save", str(task_dir), "--range", "7-9", "--final", env=env, stdin=REPORT)
    record = json.loads((task_dir / "REPORT.part-7-9.provenance.json").read_text(encoding="utf-8"))
    assert done.returncode == 0 and (task_dir / "REPORT.part-7-9.md").read_text(encoding="utf-8") == REPORT, done
    assert (task_dir / "REPORT.md").read_text(encoding="utf-8") == REPORT, "the final batch also saves REPORT.md"
    assert record["harness"] == "cursor" and record["report_check"] == "ok", record
