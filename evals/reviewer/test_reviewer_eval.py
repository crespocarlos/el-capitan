#!/usr/bin/env python3
"""The seeded-defect reviewer eval, offline: the cases, `score.py` against recorded replies, and `live.py`'s guards.

No test dispatches a persona. The recorded `sample` replies are hand-written plumbing fixtures (hits, a wrong
line, a missing keyword, a failed, missing and tainted run), not model output; a real run is the owner's `live.py`.
`live.py` is exercised against a stub harness that records its argv, prompt and working directory.
"""
from __future__ import annotations

import json
import re
import stat
import sys
from pathlib import Path

import live
import pytest
import score

SAMPLE = score.HERE / "recorded" / "sample"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def case_by_id(case_id: str) -> score.Case:
    return next(case for case in score.load_cases() if case.id == case_id)


def test_every_lens_has_three_resolvable_cases_with_specific_keywords() -> None:
    cases = score.load_cases()
    for persona in score.PERSONAS:
        assert sum(case.lens == persona for case in cases) >= score.MIN_CASES, persona
    for case in cases:
        files = {**case.context, **case.after, **({"SPEC.md": case.text()} if case.kind == "spec" else {})}
        assert case.lens in score.PERSONAS and case.keywords and all(case.keywords), case.id
        generic = {term for group in case.keywords for term in group if term.rstrip("*").lower() in score.GENERIC_TERMS}
        assert not generic, (case.id, generic)
        for path, line in case.locations:
            assert 1 <= line <= len(files[path].splitlines()), (case.id, path, line)
        if case.kind == "spec":
            assert case.refs and case.hand_seeded and len(case.keywords) >= 2, case.id
        assert case.hand_seeded == case.source.startswith("hand-seeded"), case.id


def test_each_diff_agrees_with_the_files_after_it() -> None:
    """Every new-side line of every hunk is that line of the case's `after` file, so the two copies cannot drift."""
    for case in (case for case in score.load_cases() if case.kind == "diff"):
        after = {path: text.splitlines() for path, text in case.after.items()}
        path, line, checked = "", 0, 0
        for row in case.text().splitlines():
            header = HUNK.match(row)
            if row.startswith("+++ b/"):
                path = row[6:]
            elif header:
                line = int(header.group(1))
            elif row.startswith(("+", " ")) and path:
                assert after[path][line - 1] == row[1:], (case.id, path, line)
                line, checked = line + 1, checked + 1
        assert after and checked, case.id


def test_the_scorer_reads_recorded_replies_per_run() -> None:
    result = score.tally(SAMPLE, score.load_cases())
    adversarial, scope = result["adversarial"], result["specwriter-scope"]
    assert adversarial["cases"]["status-guard-cr-heading"] == [True, False, False], "wrong line and wrong keywords miss"
    assert adversarial["cases"]["force-before-approval"] == [True, True, False], "an absolute anchor counts"
    assert adversarial["runs"] == [0.333, 0.167, 0.0] and adversarial["mean"] == 0.167
    assert "force-before-approval run-3" in adversarial["missing"], "a missing reply is a listed miss"
    assert scope["cases"]["spec-task-order"] == [True, False, False], "a clean pass and a tainted hit both miss"
    assert scope["tainted"] == ["spec-task-order run-3"]
    assert set(result) == {"adversarial", "specwriter-scope"}, "a persona with no replies is not scored"


@pytest.mark.parametrize("reply", [
    # An unrelated finding at the defect's line, quoting the regex (which holds \r) only in code.
    "1. [attention · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** — a MultiEdit payload skips the heading check\n"
    "```\nSTATUS = re.compile(r\"^(## Status[ \\t]*\\r?\\n)\")\n```\nThe parser never sees `edits[]` or `\\r CR`.\n"
    "Fix: apply the edits.\n",
    # The right defect, anchored at a range that covers the whole file rather than the line.
    "1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:1-40`** — the awk misses a CR heading\nFix: x.\n",
    # The right words, but only in text after the last finding ends.
    "1. [nit · 2] **`.claude/hooks/check-task-spec-owner.sh:27`** — the comment is long\nFix: shorten it.\n\n"
    "Also, the awk heading reader and a CR heading disagree.\n",
])
def test_a_finding_at_the_right_spot_about_something_else_is_not_a_catch(reply: str) -> None:
    assert not score.catches(reply, case_by_id("status-guard-cr-heading"))


def test_the_bar_needs_the_runs_the_mean_and_every_always_caught_case() -> None:
    caught = {"a": [True, True, True], "b": [True, False, False]}
    baseline = {"adversarial": {"runs": [0.6] * 3, "mean": 0.6, "spread": 0.2, "cases": caught}}
    kept = {"a": [True] * 3, "b": [False] * 3}
    held = {"adversarial": {"runs": [0.45] * 3, "mean": 0.45, "spread": 0.0, "cases": kept}}
    assert score.compare(baseline, held) == {"adversarial": []}
    fell = {"adversarial": {"runs": [0.3], "mean": 0.3, "spread": 0.0, "cases": {"a": [False], "b": [True]}}}
    problems = score.compare(baseline, fell)["adversarial"]
    assert any("1 run(s) against the baseline's 3" in p for p in problems), problems
    assert any("below 0.4" in p for p in problems) and any(p.startswith("a:") for p in problems)


def test_against_needs_a_baseline_with_replies(tmp: Path, capsys) -> None:
    assert score.main([str(SAMPLE), "--against", str(tmp / "missing")]) == 2
    assert score.main([str(SAMPLE), "--against", str(tmp)]) == 2
    assert "no recorded replies" in capsys.readouterr().err


STUB = """#!{python}
import json, os, pathlib, sys
log = pathlib.Path(os.environ["STUB_LOG"])
log.joinpath("argv.json").write_text(json.dumps(sys.argv[1:]))
log.joinpath("prompt.txt").write_text(sys.stdin.read())
log.joinpath("files.txt").write_text("\\n".join(sorted(str(p) for p in pathlib.Path(".").rglob("*") if p.is_file())))
mode = os.environ.get("STUB_MODE", "ok")
if mode == "fail":
    print("partial output")
    sys.exit(1)
if mode == "taint":
    tool = {{"type": "tool_use", "name": "Read", "input": {{"file_path": "/etc/hosts"}}}}
    print(json.dumps({{"type": "assistant", "message": {{"content": [tool]}}}}))
print(json.dumps({{"type": "result", "result": pathlib.Path(os.environ["STUB_REPLY"]).read_text()}}))
"""


@pytest.fixture
def harness(tmp: Path, monkeypatch) -> Path:
    """A stub `claude` that logs what it was given and answers per `STUB_MODE`."""
    stub = tmp / "claude"
    stub.write_text(STUB.format(python=sys.executable))
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    (tmp / "log").mkdir()
    monkeypatch.setenv("STUB_LOG", str(tmp / "log"))
    monkeypatch.delenv("CI", raising=False)
    return stub


def reply_for(case: score.Case) -> str:
    """A reply that catches `case`: its first location and one term of each keyword group, in prose."""
    path, line = case.locations[0]
    words = " ".join(group[0].rstrip("*") for group in case.keywords)
    return f"1. [attention · 4] **`{path}:{line}`** — {words}\nFix: address it.\n"


def test_the_live_run_spends_nothing_without_the_flag_and_never_under_ci(tmp: Path, monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setattr(live.subprocess, "run", lambda *a, **k: calls.append(a))
    assert live.main(["--persona", "architecture", "--out", str(tmp)]) == 0
    assert "0 already recorded, 9 to dispatch" in capsys.readouterr().out and not calls and not any(tmp.iterdir())
    monkeypatch.setenv("CI", "true")
    assert live.main(["--yes-spend", "--persona", "architecture", "--out", str(tmp)]) == 2 and not calls


def test_the_live_run_is_isolated_records_scores_and_skips_what_it_has(tmp: Path, harness: Path, monkeypatch,
                                                                       capsys) -> None:
    case = case_by_id("install-prune-user-folders")
    (tmp / "reply.md").write_text(reply_for(case))
    monkeypatch.setenv("STUB_REPLY", str(tmp / "reply.md"))
    argv = ["--yes-spend", "--case", case.id, "--runs", "1", "--label", "t", "--out", str(tmp / "rec"),
            "--claude", str(harness)]
    assert live.main(argv) == 0
    sent = json.loads((tmp / "log" / "argv.json").read_text())
    for flag in ("--restricted", "--strict-mcp-config", "--disable-slash-commands", "--tools", "--agents"):
        assert flag in sent, flag
    agents = json.loads(sent[sent.index("--agents") + 1])
    assert agents["reviewer-architecture"]["tools"] == ["Read", "Grep", "Glob"]
    prompt = (tmp / "log" / "prompt.txt").read_text().replace(live.NO_LOOKUPS.strip(), "")
    assert live.NO_LOOKUPS.strip() in (tmp / "log" / "prompt.txt").read_text(), "the persona is told what it lacks"
    assert "code index" not in prompt and "mcp__" not in prompt and "+++ b/install.sh" in prompt
    assert "install.sh" in (tmp / "log" / "files.txt").read_text(), "the persona can read the changed file"
    assert "mean 1.00" in capsys.readouterr().out
    assert live.main(argv) == 0 and "1 already recorded, 0 to dispatch" in capsys.readouterr().out
    monkeypatch.setenv("STUB_MODE", "taint")
    assert live.main([*argv, "--redo"]) == 0
    out = capsys.readouterr().out
    assert "(tainted)" in out and "mean 0.00" in out, "a run that read outside its case is a listed miss"


def test_the_live_run_stops_after_three_failures_in_a_row(tmp: Path, harness: Path, monkeypatch) -> None:
    monkeypatch.setenv("STUB_MODE", "fail")
    assert live.main(["--yes-spend", "--persona", "architecture", "--label", "t", "--out", str(tmp / "rec"),
                      "--claude", str(harness)]) == 3
    records = sorted((tmp / "rec").rglob("run-*.md"))
    assert len(records) == 3 and all("partial output" in path.read_text() for path in records)
    reply, meta = live.dispatch(str(tmp / "nowhere"), case_by_id("install-prune-user-folders"), 5)
    assert reply.startswith(live.FAILED) and meta["exit"] is None, "a harness that cannot start is a failed record"
