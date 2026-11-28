#!/usr/bin/env python3
"""Every crew agent's reply and usage is captured, in Cursor and in Claude Code.

`capture-reply.sh` reads Cursor's `subagentStop` (a transcript of `role` lines, `subagent_id`, `subagent_type`, the
counts but no tokens) as it reads Claude Code's `SubagentStop`: each agent kind lands where its orchestrator reads it,
a marker with no `.expect` saves nothing, the latest reply to a marker is the reply (the earlier one `.prev.md`), a
reply that answers nothing leaves `.unanswered` and asks once for the reply, the subagent's transcript is found when
the payload's path misses, a repeated stop changes nothing, and a stale Cursor install drops with a logged line.
`cursor-usage.sh` records each Cursor `stop`'s raw counts on its conversation's first task; readers count only rises.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest
from cli_runner import launcher
from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "src" / "crew"
FINDINGS = TOOLS / "review" / "crew_review_findings.py"
TASK = TOOLS / "task" / "crew_task.py"
LS = TOOLS / "task" / "crew_ls.py"
HOOK = ROOT / ".claude" / "hooks" / "capture-reply.sh"
USAGE_HOOK = ROOT / ".claude" / "hooks" / "cursor-usage.sh"
PERSONA_REPLY = "### Findings: none\n\nAssessment: approve — nothing in this lane.\n"
CRITIC_REPLY = "Verdict: pass\n\n1. [Consider] The verify line could name the test file.\n"
EXPLORER_REPLY = "## Files involved\n- a.py\n\n## Tests\n- test_a.py\n"
POINTER = "The findings are listed above.\n"
REPORT = ("## Implementation Report\n\n**Tasks:** 1/1 passed\n**Harness:** cursor\n\n### Quality gates\ntest exit=0\n"
          "- `test` — pass\n\n### Unverified claims\nnone\n\n### Report data\n```json\n"
          '{"schema_version": 1, "tasks": {"passed": 1, "total": 1}, "gates": [{"name": "test", "exit": 0}]}\n```\n')


def world(tmp: Path) -> tuple[Path, Path]:
    """A HOME with the crew tools on its bin path and one IMPLEMENTING task with a gates file."""
    home = tmp / "home"
    (home / ".agent" / "bin").mkdir(parents=True)
    for name in ("crew-review-findings.py", "crew-task.py"):
        (home / ".agent" / "bin" / name).symlink_to(launcher(name))
    task = home / ".agent" / "tasks" / "T"
    task.mkdir(parents=True)
    (task / "SPEC.md").write_text("# T\n\n## Status\nIMPLEMENTING\n", encoding="utf-8")
    (task / "gates.json").write_text(json.dumps({"schema_version": 1, "gates": [{"name": "test", "exit": 0}]}),
                                     encoding="utf-8")
    return home, task


def marker(directory: Path, name: str, home: Path) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    done = cli(FINDINGS, "expect", "--review-dir", str(directory), "--persona", name, env={"HOME": str(home)})
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def cursor_lines(prompt: str, replies: list[str]) -> list[str]:
    """Cursor's shape: a wrapped user query, assistant turns of text and tool calls, then `turn_ended`."""
    lines = [{"role": "user", "message": {"content": [
        {"type": "text", "text": f"<timestamp>2026-11-28</timestamp>\n<user_query>\n{prompt}\n</user_query>"}]}}]
    for reply in replies:
        lines.append({"role": "assistant", "message": {"content": [
            {"type": "text", "text": reply},
            {"type": "tool_use", "name": "UpdateCurrentStep", "input": {"current_step": "done"}}]}})
    lines.append({"type": "turn_ended", "status": "success"})
    return [json.dumps(line) for line in lines]


def cursor_transcript(path: Path, prompt: str, replies: list[str]) -> Path:
    path.write_text("".join(line + "\n" for line in cursor_lines(prompt, replies)), encoding="utf-8")
    return path


def claude_transcript(path: Path, prompt: str, reply: str) -> Path:
    usage = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    lines = [{"type": "user", "timestamp": "2026-11-28T10:00:00.500Z", "message": {"role": "user", "content": prompt}},
             {"type": "assistant", "message": {"id": "m1", "role": "assistant", "model": "m-1", "usage": usage,
                                               "content": [{"type": "text", "text": reply}]}}]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def run_hook(home: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                          env={**os.environ, "HOME": str(home)})


def cursor_stop(home: Path, transcript: Path, agent: str = "s1", kind: str = "generalPurpose",
                extra: dict | None = None) -> subprocess.CompletedProcess:
    return run_hook(home, {"hook_event_name": "subagentStop", "cursor_version": "2.1.0", "subagent_id": agent,
                           "subagent_type": kind, "agent_transcript_path": str(transcript), "status": "completed",
                           "duration_ms": 61000, "tool_call_count": 7, "message_count": 9, "loop_count": 2,
                           **(extra or {})})


def claude_stop(home: Path, transcript: Path, agent: str, kind: str) -> subprocess.CompletedProcess:
    return run_hook(home, {"hook_event_name": "SubagentStop", "agent_id": agent, "agent_type": kind,
                           "agent_transcript_path": str(transcript)})


def state(home: Path, name: str) -> str:
    path = home / ".agent" / "state" / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def progress(task: Path) -> str:
    path = task / "PROGRESS.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# (agent kind, the directory under the task, the name its marker carries, the reply, the file it lands in)
KINDS = [
    ("reviewer-adversarial", "review/1", "adversarial", PERSONA_REPLY, "adversarial.out.md"),
    ("reviewer-explorer", "review/1/claims/1", "explorer", "## Similar patterns\n- a.py:3 does the same\n",
     "explorer.out.md"),
    ("reviewer-probe", "review/1", "probe", "observed: exit 0\n", "probe.out.md"),
    ("specwriter-scope", "spec-agents/1", "specwriter-scope", CRITIC_REPLY, "specwriter-scope.out.md"),
    ("specwriter-adversarial", "spec-agents/1", "specwriter-adversarial", CRITIC_REPLY,
     "specwriter-adversarial.out.md"),
    ("specwriter-explorer", "spec-agents/1", "specwriter-explorer", EXPLORER_REPLY, "specwriter-explorer.out.md"),
]


@pytest.mark.parametrize("harness", ["cursor", "claude-code"])
@pytest.mark.parametrize("kind, place, name, reply, saved", KINDS, ids=[row[0] for row in KINDS])
def test_each_agent_kind_lands_where_its_orchestrator_reads_it(tmp: Path, harness: str, kind: str, place: str,
                                                               name: str, reply: str, saved: str) -> None:
    """The marker's reply is saved in its directory with the harness, agent id, model and nonce; `.expect` stays, no
    `.unanswered` is left, the run's `agent_end` (tokens unknown in Cursor) goes to the task, and Cursor's stdout is
    `{}` with the line logged."""
    home, task = world(tmp)
    directory = task / place
    line = marker(directory, name, home)
    prompt = f"{line}\ncrew-task: {task}\n\nDo the work."
    if harness == "cursor":
        done = cursor_stop(home, cursor_transcript(tmp / "t.jsonl", prompt, ["Reading.", reply]), "s1", kind,
                           {"subagent_model": "model-x"})
        assert (done.returncode, done.stdout) == (0, "{}\n"), done
    else:
        done = claude_stop(home, claude_transcript(tmp / "t.jsonl", prompt, reply), "s1", kind)
        assert done.returncode == 0 and "capture-reply: saved" in done.stdout, done
    assert (directory / saved).read_text(encoding="utf-8") == reply
    record = json.loads((directory / saved.replace(".out.md", ".provenance.json")).read_text(encoding="utf-8"))
    model = "model-x" if harness == "cursor" else "m-1"
    assert (record["harness"], record["agent_id"], record["model"], record["nonce"]) == \
        (harness, "s1", model, line.split()[-1]), record
    assert (directory / f"{name}.expect").exists() and not (directory / f"{name}.unanswered").exists()
    assert "capture-reply: saved" in state(home, "capture-reply.log")
    ends = [entry for entry in progress(task).splitlines() if "agent_end" in entry]
    expected = (r"tokens=unknown duration_ms=61000 tool_calls=7 messages=9 started=\S+Z harness=cursor"
                if harness == "cursor" else "tokens=150 input=100 output=50 cache_read=0 cache_write=0 "
                "started=2026-11-28T10:00:00Z first_input=100 first_cache_read=0 first_cache_write=0 "
                "harness=claude-code")
    assert len(ends) == 1 and re.search(f"agent={kind} persona={name} agent_id=s1 {expected}$", ends[0]), ends


def test_a_cursor_builder_report_is_saved_from_its_transcript(tmp: Path) -> None:
    """Cursor's `subagent_type` `crew-builder` and its last assistant text: REPORT.md with `harness: cursor`."""
    home, task = world(tmp)
    transcript = cursor_transcript(tmp / "b.jsonl", f"crew-task: {task}\n\nImplement T1.",
                                   ["Working.", "Done.\n\n" + REPORT])
    done = cursor_stop(home, transcript, "b1", "crew-builder")
    assert (done.returncode, done.stdout) == (0, "{}\n"), done
    assert (task / "REPORT.md").read_text(encoding="utf-8") == REPORT
    record = json.loads((task / "REPORT.provenance.json").read_text(encoding="utf-8"))
    assert (record["harness"], record["agent_id"], record["report_check"]) == ("cursor", "b1", "ok"), record


def test_claude_codes_last_assistant_message_is_the_reply_when_the_transcript_lags(tmp: Path) -> None:
    """Claude Code's transcript is written asynchronously: it holds only the dispatch prompt (the marker) when the
    hook fires, and the documented `last_assistant_message` carries the reply, saved with `source: hook`."""
    home, task = world(tmp)
    directory = task / "review" / "1"
    prompt = marker(directory, "adversarial", home) + "\nReview."
    path = tmp / "lag.jsonl"
    path.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n",
                    encoding="utf-8")
    done = run_hook(home, {"hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": "reviewer-adversarial",
                           "stop_hook_active": False, "agent_transcript_path": str(path),
                           "last_assistant_message": PERSONA_REPLY})
    assert done.returncode == 0 and "capture-reply: saved" in done.stdout, done
    assert (directory / "adversarial.out.md").read_text(encoding="utf-8") == PERSONA_REPLY
    record = json.loads((directory / "adversarial.provenance.json").read_text(encoding="utf-8"))
    assert (record["source"], record.get("reply_from")) == ("hook", None), record


@pytest.mark.parametrize("harness", ["cursor", "claude-code"])
def test_a_quoted_marker_with_no_expect_saves_nothing(tmp: Path, harness: str) -> None:
    """A non-crew subagent whose prompt quotes a marker line: no `.expect` holds its nonce, so nothing is written."""
    home, task = world(tmp)
    directory = task / "spec-agents" / "1"
    directory.mkdir(parents=True)
    prompt = f"Explain this line:\ncrew-review-out: {directory} specwriter-scope {'a' * 32}\n"
    if harness == "cursor":
        done = cursor_stop(home, cursor_transcript(tmp / "q.jsonl", prompt, [CRITIC_REPLY]))
    else:
        done = claude_stop(home, claude_transcript(tmp / "q.jsonl", prompt, CRITIC_REPLY), "q1", "general-purpose")
    assert done.returncode == 0 and not (directory / "specwriter-scope.out.md").exists(), done
    assert "no specwriter-scope.expect for this marker; nothing saved" in state(home, "capture-reply.log")
    assert progress(task) == ""


@pytest.mark.parametrize("name, place, first, again, second_agent", [
    ("adversarial", "review/1", POINTER, PERSONA_REPLY, "s1"),
    ("adversarial", "review/1", PERSONA_REPLY, "### Findings: none\n\nAssessment: approve — re-checked.\n", "s1"),
    ("adversarial", "review/1", PERSONA_REPLY, "### Findings: none\n\nAssessment: approve — corrected.\n", "s9"),
    ("specwriter-scope", "spec-agents/1", "I could not finish.\n", CRITIC_REPLY, "s1"),
    ("specwriter-scope", "spec-agents/1", CRITIC_REPLY, "Verdict: pass\n\nNothing more.\n", "s9"),
], ids=["a pointer is replaced", "an answered persona is replaced, kept as prev", "a resume with a new agent id",
        "a critic with no verdict is replaced", "an answered critic's resume under a new id"])
def test_the_latest_reply_to_a_marker_is_the_reply(tmp: Path, name: str, place: str, first: str, again: str,
                                                    second_agent: str) -> None:
    """A second stop for the same marker (a resume, whatever its agent id) becomes `<name>.out.md`, the earlier reply
    `<name>.prev.md` with its record; the same reply a third time saves nothing more."""
    home, task = world(tmp)
    directory = task / place
    prompt = marker(directory, name, home) + "\nDo the work."
    path = tmp / "r.jsonl"
    cursor_stop(home, cursor_transcript(path, prompt, [first]))
    cursor_stop(home, cursor_transcript(path, prompt, [first, again]), second_agent)
    assert (directory / f"{name}.out.md").read_text(encoding="utf-8") == again
    assert (directory / f"{name}.prev.md").read_text(encoding="utf-8") == first
    record = json.loads((directory / f"{name}.provenance.json").read_text(encoding="utf-8"))
    assert (record["resumed"], record["agent_id"], record["harness"]) == (True, second_agent, "cursor"), record
    assert (directory / f"{name}.prev.provenance.json").exists()
    assert not (directory / f"{name}.unanswered").exists() and (directory / f"{name}.expect").exists()
    cursor_stop(home, cursor_transcript(path, prompt, [first, again]), second_agent)
    assert "already saved" in state(home, "capture-reply.log")
    assert (directory / f"{name}.prev.md").read_text(encoding="utf-8") == first


def conversation(tmp: Path, prompt: str, replies: list[str], flat: bool = False) -> tuple[Path, Path]:
    """Cursor's layout: the parent `<conv>/<conv>.jsonl` (or a flat `<conv>.jsonl`) and `<conv>/subagents/s1.jsonl`."""
    root = tmp / "agent-transcripts"
    parent = root / ("c1.jsonl" if flat else "c1/c1.jsonl")
    parent.parent.mkdir(parents=True, exist_ok=True)
    cursor_transcript(parent, "crew review this branch", ["Dispatching."])
    (root / "c1" / "subagents").mkdir(parents=True, exist_ok=True)
    return parent, cursor_transcript(root / "c1" / "subagents" / "s1.jsonl", prompt, replies)


def native(transcript_path: str | None, **fields) -> dict:
    """A Cursor `subagentStop` payload with both ids, status `completed` and loop 0, minus the fields given as None."""
    payload = {"hook_event_name": "subagentStop", "cursor_version": "2.1.0", "subagent_id": "s1",
               "child_conversation_id": "s1", "subagent_type": "generalPurpose", "status": "completed",
               "transcript_path": transcript_path, "duration_ms": 1000, "tool_call_count": 1, "message_count": 2,
               "loop_count": 0, **fields}
    return {key: value for key, value in payload.items() if value is not None or key == "agent_transcript_path"}


@pytest.mark.parametrize("case", ["null", "empty", "the parent's", "missing file", "flat parent, env only",
                                  "no subagent_id: nonce scan", "no transcript: summary", "live: parent conversation id"])
def test_the_subagent_transcript_is_found_when_agent_transcript_path_misses(tmp: Path, case: str) -> None:
    """`agent_transcript_path` null, empty, the parent's or a missing file: the reply is read from
    `<conv>/subagents/<subagent_id>.jsonl` (from `transcript_path`, or `$CURSOR_TRANSCRIPT_PATH` for a flat parent),
    else the folder's file carrying the `task` field's nonce; with no transcript, a completed run's `summary` is saved
    as `reply_from: summary` but leaves `.unanswered`, so the hook asks once for the real reply."""
    home, task = world(tmp)
    directory = task / "review" / "1"
    line = marker(directory, "adversarial", home)
    live = case.startswith("live")
    root = home / ".cursor" / "projects" / "p" if live else tmp
    parent, sub = conversation(root, line + "\nReview.", ["Reading.", PERSONA_REPLY], flat=case.startswith("flat"))
    own = {"null": None, "empty": "", "the parent's": str(parent), "missing file": str(tmp / "gone.jsonl")}
    payload = native(None if live else str(parent), agent_transcript_path=own.get(case), task=line + "\nReview.")
    env = {}
    if live:
        payload.update(subagent_id="toolu_0111", child_conversation_id="x9", parent_conversation_id="c1")
    if case.startswith("flat"):
        payload.pop("transcript_path")
        env = {"CURSOR_TRANSCRIPT_PATH": str(parent)}
    if case.startswith("no subagent_id"):
        payload.pop("subagent_id"), payload.pop("child_conversation_id")
    if case.startswith("no transcript"):
        sub.unlink()
        payload["summary"] = PERSONA_REPLY
    done = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                          env={**os.environ, "HOME": str(home), **env})
    summary = case.startswith("no transcript")
    log = state(home, "capture-reply.log")
    assert done.returncode == 0, done
    assert ("followup_message" in done.stdout) if summary else done.stdout == "{}\n", (done.stdout, log)
    assert (directory / "adversarial.out.md").read_text(encoding="utf-8") == PERSONA_REPLY, log
    assert (directory / "adversarial.unanswered").exists() is summary
    record = json.loads((directory / "adversarial.provenance.json").read_text(encoding="utf-8"))
    assert (record["source"], record.get("reply_from")) == ("hook", "summary" if summary else None), record


def test_a_transcript_that_fails_the_marker_check_is_never_read(tmp: Path) -> None:
    """`agent_transcript_path` is the parent's and no subagent file exists: the parent's text is never saved as the
    persona's reply; the dispatch stays pending and the diagnostic is logged."""
    home, task = world(tmp)
    directory = task / "review" / "1"
    line = marker(directory, "adversarial", home)
    parent, sub = conversation(tmp, line + "\nReview.", [PERSONA_REPLY])
    sub.unlink()
    cursor_transcript(parent, "crew review this branch", [PERSONA_REPLY])
    done = run_hook(home, native(str(parent), agent_transcript_path=str(parent), task=line + "\nReview."))
    assert done.returncode == 0, done
    assert not (directory / "adversarial.out.md").exists() and (directory / "adversarial.unanswered").exists()
    assert "no transcript; the marker is from the payload's task (keys=" in state(home, "capture-reply.log")


def test_a_stop_that_wrote_nothing_is_retried_by_its_repeat(tmp: Path) -> None:
    """The first fire cannot write (a read-only review directory): nothing is recorded as seen, so the identical
    second fire saves."""
    home, task = world(tmp)
    directory = task / "review" / "1"
    prompt = marker(directory, "adversarial", home)
    parent, sub = conversation(tmp, prompt, [PERSONA_REPLY])
    payload = native(str(parent), agent_transcript_path=str(sub))
    directory.chmod(0o500)
    try:
        run_hook(home, payload)
    finally:
        directory.chmod(0o700)
    assert not (directory / "adversarial.out.md").exists(), state(home, "capture-reply.log")
    assert run_hook(home, payload).returncode == 0
    log = state(home, "capture-reply.log")
    assert (directory / "adversarial.out.md").read_text(encoding="utf-8") == PERSONA_REPLY, log


def test_both_payload_variants_at_once_save_once(tmp: Path) -> None:
    """Cursor fires `subagentStop` twice, with and without `child_conversation_id`: one save, one `agent_end`, no
    `.prev.md`, and the second logs `already saved`."""
    home, task = world(tmp)
    directory = task / "review" / "1"
    prompt = f"{marker(directory, 'adversarial', home)}\ncrew-task: {task}\nReview."
    parent, sub = conversation(tmp, prompt, [PERSONA_REPLY])
    with_child = native(str(parent), agent_transcript_path=str(sub))
    without = {key: value for key, value in with_child.items() if key != "child_conversation_id"}
    runs = [subprocess.Popen(["bash", str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             env={**os.environ, "HOME": str(home)}) for _ in range(2)]
    outs = [run.communicate(json.dumps(payload))[0] for run, payload in zip(runs, (with_child, without))]
    assert outs == ["{}\n", "{}\n"]
    assert (directory / "adversarial.out.md").read_text(encoding="utf-8") == PERSONA_REPLY
    assert not (directory / "adversarial.prev.md").exists()
    assert len([entry for entry in progress(task).splitlines() if "agent_end" in entry]) == 1, progress(task)
    assert "already saved" in state(home, "capture-reply.log")


def test_a_transcript_whose_first_line_lands_after_a_second_is_saved(tmp: Path) -> None:
    """The subagent's file exists but is empty when the hook fires; its user line is written 1 s later: polled for at
    most 3 s, then saved."""
    home, task = world(tmp)
    directory = task / "review" / "1"
    prompt = marker(directory, "adversarial", home) + "\nReview."
    parent, sub = conversation(tmp, prompt, [PERSONA_REPLY])
    body = sub.read_text(encoding="utf-8")
    sub.write_text("", encoding="utf-8")
    writer = subprocess.Popen(["bash", "-c", 'sleep 1; printf "%s" "$1" > "$2"', "-", body, str(sub)])
    done = run_hook(home, native(str(parent), agent_transcript_path=None))
    writer.wait()
    assert (done.returncode, done.stdout) == (0, "{}\n"), done
    assert (directory / "adversarial.out.md").read_text(encoding="utf-8") == PERSONA_REPLY


def test_a_stop_that_saves_nothing_logs_names_and_sizes_never_content(tmp: Path) -> None:
    """A non-crew subagent: one line with the payload's key names, its ids and paths, and each candidate path with
    exists/bytes/lines, and nothing of either transcript's text."""
    home, _ = world(tmp)
    parent, sub = conversation(tmp, "find the SECRET-PROMPT word", ["SECRET-REPLY"])
    done = run_hook(home, native(str(parent), agent_transcript_path=str(tmp / "gone.jsonl")))
    assert (done.returncode, done.stdout) == (0, "{}\n"), done
    log = state(home, "capture-reply.log")
    assert "no marker; nothing saved (keys=" in log and f"subagent_id=s1 agent_transcript_path={tmp / 'gone.jsonl'} transcript_path={parent}" in log, log
    assert "parent_conversation_id=- conversation_id=- child_conversation_id=s1" in log, log
    assert f"{tmp / 'gone.jsonl'} exists=0" in log, log
    assert re.search(rf"{re.escape(str(sub))} exists=1 bytes=\d+ lines=3", log), log
    assert "SECRET" not in log and "agent_transcript_path" in log


@pytest.mark.parametrize("status", ["error", "aborted"])
def test_an_error_or_aborted_stop_saves_nothing_and_never_continues(tmp: Path, status: str) -> None:
    home, task = world(tmp)
    directory = task / "review" / "1"
    parent, sub = conversation(tmp, marker(directory, "adversarial", home), [POINTER])
    done = run_hook(home, native(str(parent), agent_transcript_path=str(sub), status=status))
    assert (done.returncode, done.stdout) == (0, "{}\n"), done
    assert not (directory / "adversarial.out.md").exists() and (directory / "adversarial.expect").exists()
    assert f"status {status}; nothing saved, the dispatch stays pending" in state(home, "capture-reply.log")


def test_an_unanswered_first_stop_asks_for_the_reply_once(tmp: Path) -> None:
    """A completed first loop whose reply answers nothing returns Cursor's `followup_message` (the dispatch rule's
    `deliver now` text); its continuation's stop does not, and its answer replaces the pointer."""
    home, task = world(tmp)
    directory = task / "review" / "1"
    prompt = marker(directory, "adversarial", home)
    parent, sub = conversation(tmp, prompt, [POINTER])
    first = run_hook(home, native(str(parent), agent_transcript_path=str(sub)))
    assert json.loads(first.stdout)["followup_message"].startswith("deliver now:"), first
    cursor_transcript(sub, prompt, [POINTER, POINTER + "Still looking."])
    again = run_hook(home, native(str(parent), agent_transcript_path=str(sub), loop_count=1))
    assert again.stdout == "{}\n" and (directory / "adversarial.unanswered").exists(), again
    cursor_transcript(sub, prompt, [POINTER, PERSONA_REPLY])
    assert run_hook(home, native(str(parent), agent_transcript_path=str(sub))).stdout == "{}\n"
    assert (directory / "adversarial.out.md").read_text(encoding="utf-8") == PERSONA_REPLY


def test_a_half_written_final_line_keeps_the_dispatch_pending(tmp: Path) -> None:
    """The stop fires while the last assistant line is still being written: that line does not parse, the interim
    text is saved, and `<name>.unanswered` marks the dispatch pending (logged) until a later reply answers it."""
    home, task = world(tmp)
    directory = task / "review" / "1"
    prompt = marker(directory, "adversarial", home) + "\nReview."
    whole = cursor_lines(prompt, ["Reading.", PERSONA_REPLY])
    path = tmp / "h.jsonl"
    path.write_text("\n".join(whole[:2]) + "\n" + whole[2][: len(whole[2]) // 2], encoding="utf-8")
    done = cursor_stop(home, path)
    assert (done.returncode, done.stdout) == (0, "{}\n"), done
    assert (directory / "adversarial.out.md").read_text(encoding="utf-8") == "Reading."
    assert (directory / "adversarial.unanswered").exists()
    assert "unanswered: adversarial.unanswered written" in state(home, "capture-reply.log")
    cursor_stop(home, cursor_transcript(path, prompt, ["Reading.", PERSONA_REPLY]))
    assert (directory / "adversarial.out.md").read_text(encoding="utf-8") == PERSONA_REPLY
    assert not (directory / "adversarial.unanswered").exists()


@pytest.mark.parametrize("body", ['{"role": "user", "message": {"content": [{"type": "text", "text": "crew-task: x',
                                  '{"role": "user", crew-review-out: x y z\nnot json either\n'],
                         ids=["a truncated line", "no JSON line"])
def test_a_malformed_transcript_is_skipped_and_logged(tmp: Path, body: str) -> None:
    home, task = world(tmp)
    path = tmp / "bad.jsonl"
    path.write_text(body, encoding="utf-8")
    done = cursor_stop(home, path)
    assert (done.returncode, done.stdout) == (0, "{}\n"), done
    assert f"malformed transcript {path}: no message line; skipped" in state(home, "capture-reply.log")
    assert progress(task) == ""


@pytest.mark.parametrize("installed", [True, False], ids=["counterpart registered", "a stale install"])
def test_the_claude_format_copy_in_cursor_never_processes(tmp: Path, installed: bool) -> None:
    """Cursor's Claude-format copy stands down for the registered counterpart; with a stale ~/.cursor/hooks.json it
    drops, logs `re-run install.sh`, and prints nothing. Only the native event saves."""
    home, task = world(tmp)
    if installed:
        (home / ".cursor").mkdir()
        (home / ".cursor" / "hooks.json").write_text(
            (ROOT / ".cursor" / "hooks.template.json").read_text(encoding="utf-8"), encoding="utf-8")
    directory = task / "review" / "1"
    transcript = cursor_transcript(tmp / "c.jsonl", marker(directory, "adversarial", home), [PERSONA_REPLY])
    copy = {"hook_event_name": "SubagentStop", "cursor_version": "2.1.0", "agent_transcript_path": str(transcript)}
    stood = run_hook(home, copy)
    assert (stood.returncode, stood.stdout, stood.stderr) == (0, "", "")
    assert not (directory / "adversarial.out.md").exists()
    assert ("re-run install.sh" in state(home, "capture-reply.log")) is not installed
    assert cursor_stop(home, transcript).returncode == 0 and (directory / "adversarial.out.md").exists()


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def usage_world(tmp: Path) -> tuple[Path, Path, Path]:
    """A checkout on `feat/x` whose task `T` records that remote and branch."""
    home, task = world(tmp)
    repo = tmp / "repo"
    repo.mkdir()
    git("init", "-q", "-b", "feat/x", cwd=repo)
    git("remote", "add", "origin", "git@example.invalid:o/r.git", cwd=repo)
    (task / ".task-id").write_text(json.dumps({"repo_remote_url": "git@example.invalid:o/r.git", "branch": "feat/x",
                                               "slug": "t", "created_at": "2026-11-28T00:00:00Z"}), encoding="utf-8")
    return home, task, repo


def stop_payload(repo: Path, generation: str, counts: tuple[int, int, int, int], conversation: str = "c1") -> dict:
    return {"hook_event_name": "stop", "cursor_version": "2.1.0", "conversation_id": conversation,
            "generation_id": generation, "model_id": "model-x", "loop_count": 1, "status": "completed",
            "workspace_roots": [str(repo)], "input_tokens": counts[0], "output_tokens": counts[1],
            "cache_read_tokens": counts[2], "cache_write_tokens": counts[3]}


def usage_stop(home: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(USAGE_HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                          env={**os.environ, "HOME": str(home)})


@pytest.mark.parametrize("series, new, cache_read", [
    ([(1000, 100, 5000, 200), (2500, 300, 9000, 200)], 3000, 9000),
    ([(1000, 100, 5000, 200), (1500, 200, 4000, 0)], 1900, 9000),
], ids=["running totals: the last values", "per-loop counts: never more than their sum"])
def test_two_consecutive_cursor_stops_are_recorded_raw_and_read_once(tmp: Path, series: list, new: int,
                                                                     cache_read: int) -> None:
    """Each `stop` appends its raw counts with its ids; a repeated `generation_id` adds nothing; the readers take each
    count's rise over the previous stop (all of it after a fall), so running totals read as their last value and
    per-loop counts as at most their sum. `crew ls --cost` and `crew report` show it approximate."""
    home, task, repo = usage_world(tmp)
    for index, counts in enumerate(series):
        done = usage_stop(home, stop_payload(repo, f"g{index}", counts))
        assert (done.returncode, done.stdout) == (0, "{}\n"), done
    usage_stop(home, stop_payload(repo, "g1", series[1]))
    lines = [line for line in progress(task).splitlines() if "cursor_stop" in line]
    assert len(lines) == 3 and "conversation_id=c1 generation_id=g0 model=model-x loop_count=1" in lines[0], lines
    cost = cli(LS, "--tasks-dir", str(task.parent), "--cost", env={"HOME": str(home)}).stdout
    shown = f"cursor sessions: new ~{round(new / 1000)}k, cache reads ~{round(cache_read / 1000)}k (2 stops)"
    assert shown in cost, cost
    report = cli(LS, "--tasks-dir", str(task.parent), "--report", "--since", "36500d", "--repo", "all",
                 env={"HOME": str(home)}).stdout
    assert shown in report, report


def test_a_conversation_stays_on_its_first_task_across_a_branch_switch(tmp: Path) -> None:
    """The first stop binds the conversation to its task in ~/.agent/state; after a switch to another task's branch
    its stops still go to the first task, so summing tasks never counts a running total twice."""
    home, task, repo = usage_world(tmp)
    other = task.parent / "U"
    other.mkdir()
    (other / "SPEC.md").write_text("# U\n\n## Status\nIMPLEMENTING\n", encoding="utf-8")
    (other / ".task-id").write_text(json.dumps({"repo_remote_url": "git@example.invalid:o/r.git", "branch": "feat/y",
                                                "slug": "u", "created_at": "2026-11-28T00:00:00Z"}), encoding="utf-8")
    usage_stop(home, stop_payload(repo, "g0", (1000, 100, 0, 0)))
    git("checkout", "-q", "-b", "feat/y", cwd=repo)
    usage_stop(home, stop_payload(repo, "g1", (1500, 200, 0, 0)))
    usage_stop(home, stop_payload(repo, "g2", (10, 1, 0, 0), "c2"))
    assert len([line for line in progress(task).splitlines() if "cursor_stop" in line]) == 2
    assert [line for line in progress(other).splitlines() if "cursor_stop" in line][0].count("conversation_id=c2")
    assert f"c1 {task}" in state(home, "cursor-conversations.txt")


@pytest.mark.parametrize("missing", ["conversation_id", "generation_id"])
def test_a_stop_missing_an_id_is_skipped_and_logged(tmp: Path, missing: str) -> None:
    home, task, repo = usage_world(tmp)
    payload = {key: value for key, value in stop_payload(repo, "g0", (1, 1, 1, 1)).items() if key != missing}
    assert usage_stop(home, payload).stdout == "{}\n"
    assert progress(task) == ""
    assert "no conversation_id or generation_id in the payload; skipped" in state(home, "cursor-usage.log")


def test_a_cursor_stop_without_a_task_records_nothing_and_logs_nothing(tmp: Path) -> None:
    home, task, repo = usage_world(tmp)
    git("checkout", "-q", "-b", "other", cwd=repo)
    done = usage_stop(home, stop_payload(repo, "g0", (1, 1, 1, 1)))
    assert (done.returncode, done.stdout) == (0, "{}\n") and progress(task) == "", done
    assert state(home, "cursor-usage.log") == "" and state(home, "cursor-conversations.txt") == ""


def test_gc_telemetry_prunes_the_hook_logs_by_age(tmp: Path) -> None:
    """`crew-task.py gc --only telemetry --apply` drops each hook log's lines older than `sessions_days`, keeps the
    rest, and leaves a log with nothing old untouched."""
    home, _ = world(tmp)
    logs = home / ".agent" / "state"
    logs.mkdir(parents=True)
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 40 * 86400))
    new = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (logs / "capture-reply.log").write_text(f"{old} SubagentStop a\n{new} SubagentStop b\n", encoding="utf-8")
    (logs / "cursor-usage.log").write_text(f"{new} usage: c\n", encoding="utf-8")
    dry = cli(TASK, "gc", "--only", "telemetry", env={"HOME": str(home)})
    assert "would prune" in dry.stdout and "capture-reply.log" in dry.stdout and "cursor-usage.log" not in dry.stdout
    done = cli(TASK, "gc", "--only", "telemetry", "--apply", env={"HOME": str(home)})
    assert done.returncode == 0, done
    assert (logs / "capture-reply.log").read_text(encoding="utf-8") == f"{new} SubagentStop b\n"
    assert (logs / "cursor-usage.log").read_text(encoding="utf-8") == f"{new} usage: c\n"


def test_the_readers_label_both_harnesses_per_agent_kind(tmp: Path) -> None:
    """A Claude Code builder with tokens and a Cursor builder without: `crew ls --cost` and `crew report` list each
    kind with its harness, and the Cursor one adds nothing to the token totals."""
    home, task = world(tmp)
    (task / "PROGRESS.md").write_text(
        "[2026-11-28T10:00:00Z] METRIC: stage_start stage=implement\n"
        "[2026-11-28T10:30:00Z] METRIC: agent_end agent=crew-builder persona=crew-builder agent_id=a1 tokens=9000 "
        "input=1000 output=2000 cache_read=40000 cache_write=4000 harness=claude-code\n"
        "[2026-11-28T11:00:00Z] METRIC: agent_end agent=crew-builder persona=crew-builder agent_id=s1 tokens=unknown "
        "duration_ms=600000 tool_calls=31 messages=40 harness=cursor\n", encoding="utf-8")
    cost = cli(LS, "--tasks-dir", str(task.parent), "--cost", env={"HOME": str(home)}).stdout
    assert ("T: new 7k, cache reads 40k; implement: 1 workers, new 7k; agents: crew-builder (claude-code) 1 run, "
            "new 7k, cache reads 40k / crew-builder (cursor) 1 run, tokens unknown, 31 tool calls, 10m") in cost, cost
    report = cli(LS, "--tasks-dir", str(task.parent), "--report", "--since", "36500d", "--repo", "all",
                 env={"HOME": str(home)}).stdout
    assert "agent crew-builder (claude-code): 1 run, new 7k, cache reads 40k" in report, report
    assert "agent crew-builder (cursor): 1 run, tokens unknown, 31 tool calls, 10m" in report, report
