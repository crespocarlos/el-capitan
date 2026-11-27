#!/usr/bin/env python3
"""The seeded-defect reviewer eval, offline: the cases, `score.py` against recorded replies, and `live.py`'s guards.

No test dispatches a persona. The recorded `sample` replies are hand-written plumbing fixtures (hits, a wrong
line, a missing keyword, a failed, missing and tainted run), not model output; a real run is the owner's `live.py`.
`live.py` is exercised against a stub harness that records its argv, prompt and working directory.
"""
from __future__ import annotations

import dataclasses
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
        assert not case.match_code or case.hand_seeded, f"{case.id}: match_code is for hand-seeded design cases"


def test_a_design_case_matches_its_keywords_inside_code_spans() -> None:
    """`match_code` is a property of the case: a design reply names its mechanism in backticks, so for such a case
    a keyword inside code counts; for any other case code stays a quote and does not."""
    plain = case_by_id("spec-task-order")
    design = dataclasses.replace(plain, match_code=True)
    reply = ("**Task 1 / Task 3** — reorder so `slug_from_url` exists before Task 1 runs\n\n"
             "Task 1's verify fails because the function arrives two tasks later.\n\nMove Task 3 first.\n")
    assert score.catches(reply, design) and not score.catches(reply, plain)
    loaded = score.load_case(plain.directory)
    assert loaded.match_code is False, "a case without the key keeps prose-only matching"


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


# Exempt from the `## Attacks` section, as `persona-authoring.md` documents: the reference shape, and the workers.
ATTACK_SHAPE_EXEMPT = ("reviewer-adversarial", "reviewer-explorer", "reviewer-layers", "reviewer-probe",
                       "specwriter-explorer")


def test_every_persona_fits_the_attack_shape() -> None:
    """Every reviewer and critic file stays at most 6 KB, so its attacks are not buried (the shared rules live in
    the contracts appended to every dispatch), and every lens but the documented exemptions has `## Attacks`."""
    files = sorted([*live.AGENTS_DIR.glob("reviewer-*.md"), *live.AGENTS_DIR.glob("specwriter-*.md")])
    assert {path.stem for path in files} >= set(live.AGENTS.values())
    assert {path.stem: path.stat().st_size for path in files if path.stat().st_size > 6 * 1024} == {}
    shapeless = [path.stem for path in files if path.stem not in ATTACK_SHAPE_EXEMPT
                 and not re.search(r"^## Attacks$", path.read_text(encoding="utf-8"), re.M)]
    assert shapeless == []
    guide = (live.AGENTS_DIR / "crew-reviewer" / "references" / "persona-authoring.md").read_text(encoding="utf-8")
    assert [name for name in ATTACK_SHAPE_EXEMPT if f"`{name}`" not in guide] == [], "an undocumented exemption"


def test_the_scorer_reads_recorded_replies_per_run() -> None:
    result = score.tally(SAMPLE, score.load_cases())
    adversarial, scope = result["adversarial"], result["specwriter-scope"]
    assert adversarial["cases"]["status-guard-cr-heading"] == [True, False, False], "wrong line and wrong keywords miss"
    assert adversarial["cases"]["force-before-approval"] == [True, True, False], "an absolute anchor counts"
    own = sum(case.lens == "adversarial" for case in score.load_cases())  # the rate's denominator: every own case
    assert adversarial["runs"] == [round(2 / own, 3), round(1 / own, 3), 0.0]
    assert adversarial["mean"] == round((3 / own) / 3, 3)
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


def test_the_scorer_counts_findings_and_the_ones_at_no_case_location() -> None:
    """Per reply, over the replies recall scores: a failure record and a tainted run are left out; a finding counts as
    matched when it anchors at a case location, whatever it says."""
    result = score.tally(SAMPLE, score.load_cases())
    adversarial, scope = result["adversarial"], result["specwriter-scope"]
    # Five replies hold 1 + 1 + 2 + 1 + 1 findings; only cr-heading run-2's anchor (line 10) is far from line 27.
    assert (adversarial["findings"], adversarial["unmatched"]) == (1.2, 0.2)
    # spec-task-too-wide holds only a failure record, spec-task-order run-3 is tainted; runs 1 and 2 hold 1 and 0.
    assert (scope["findings"], scope["unmatched"]) == (0.5, 0.0)
    empty = "Assessment: approve — nothing here.\n### Findings: none\n"
    assert score.volume(empty, case_by_id("force-before-approval")) == (0, 0)


@pytest.mark.parametrize(("persona", "fields", "rise", "fails"), [
    ("adversarial", {"unmatched": 0.7}, None, False),  # a 0.2 baseline: the +0.5 floor allows more than 1.5x
    ("adversarial", {"unmatched": 0.71}, None, True),
    ("specwriter-scope", {"unmatched": 0.5}, None, False),  # a clean baseline does not demand zero noise forever
    ("specwriter-scope", {"unmatched": 0.51}, None, True),
    ("adversarial", {"unmatched": 3.0}, "inside", True),  # a recall rise inside one spread exempts nothing
    ("adversarial", {"unmatched": 3.0}, "past", False),  # a rise past one spread does
])
def test_the_bar_fails_more_noise_without_more_recall(persona: str, fields: dict, rise: str | None,
                                                     fails: bool) -> None:
    baseline = score.tally(SAMPLE, score.load_cases())
    before = baseline[persona]
    if rise:  # the mean, relative to the baseline's own mean and spread, so the row holds for any case count
        fields = {**fields, "mean": before["mean"] + (0.01 if rise == "inside" else before["spread"] + 0.01)}
    candidate = {**baseline, persona: {**before, **fields}}
    problems = score.compare(baseline, candidate)[persona]
    assert any(p.startswith("unmatched findings per reply rose") for p in problems) == fails, problems


def test_against_prints_and_records_the_noise_counts(capsys) -> None:
    assert score.noise_allowed(4.0) == 6.0 and score.noise_allowed(0.0) == score.NOISE_FLOOR
    assert score.main([str(SAMPLE), "--against", str(SAMPLE)]) == 0
    assert "noise adversarial: findings/reply 1.2 -> 1.2, unmatched/reply 0.2 -> 0.2" in capsys.readouterr().out
    assert score.main([str(SAMPLE), "--against", str(SAMPLE), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["noise"]["specwriter-scope"] == {"findings": [0.5, 0.5],
                                                                                "unmatched": [0.0, 0.0]}


def test_a_critic_finding_is_located_by_the_reference_it_names() -> None:
    """The bold reference may quote a glob (`*` inside it), and a ref anywhere on its first line locates it; a
    `SPEC.md:N` near the defect also counts, but no line number is required."""
    case = case_by_id("spec-task-order")
    reply = ("**Critical**\n\n**Files under `**/*.py`, Task 1** — the helper does not exist yet\n\n"
             "Task 1 runs its verify line before the helper is added, so the sequential loop fails there.\n\n"
             "Move it later.\n\n**Task 2** — no verify line\n\nThe builder cannot check it.\n\nAdd one.\n\n"
             "Verdict: 2 finding(s)\n")
    blocks = score.findings(reply)
    assert len(blocks) == 2 and score.located(blocks[0], case) and score.catches(reply, case)
    numbered = "**Ordering, SPEC.md:22** — the helper does not exist yet when it is called\n\nFix: reorder.\n"
    assert score.located(score.findings(numbered)[0], case)
    colon = ("**Task 1 / Task 3**: Task 1 calls the helper before Task 3 adds it\n\nThe ordering fails the "
             "sequential loop.\n\nMove Task 3 first.\n\n**Task 2**: no verify line\n\nAdd one.\n")
    blocks = score.findings(colon)
    assert len(blocks) == 2 and score.located(blocks[0], case), "a reference followed by a colon starts a finding"


def test_against_needs_a_baseline_with_replies(tmp: Path, capsys) -> None:
    assert score.main([str(SAMPLE), "--against", str(tmp / "missing")]) == 2
    assert score.main([str(SAMPLE), "--against", str(tmp)]) == 2
    assert "no recorded replies" in capsys.readouterr().err


def test_a_handoff_line_is_neither_a_finding_nor_part_of_the_last_one() -> None:
    """The reviewer contract's handoff follows the findings; it must not lengthen the last finding or add one."""
    reply = ("Assessment: comment — the change is fine in this lane; one defect belongs to another lens.\n"
             "Read beyond the package: `a.py`\n\n"
             "1. [needs more info · 2] **`a.py:3`** — is the empty branch meant to return None?\n"
             "A caller that iterates the result fails on None.\n"
             "Handoff to adversarial: a.py:9 — a partial write truncates the cache\n")
    blocks = score.findings(reply)
    assert len(blocks) == 1 and "Handoff" not in blocks[0] and "a.py:9" not in blocks[0]


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
if mode == "audit":
    tools = [{{"type": "tool_use", "name": "Read", "input": {{"file_path": os.path.join(os.getcwd(), "install.sh")}}}},
             {{"type": "tool_use", "name": "Grep", "input": {{"pattern": "rm -rf", "path": os.getcwd()}}}},
             {{"type": "text", "text": "thinking"}}]
    print(json.dumps({{"type": "assistant", "message": {{"content": tools}}}}))
    print(json.dumps({{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "Glob", "input": {{"pattern": "**/*.sh"}}}}]}}}}))
if mode == "typo":
    real = os.path.realpath(os.getcwd())  # the harness reports the resolved working directory
    wrong = real[:-1] + ("x" if real[-1] != "x" else "y")
    calls = [{{"type": "tool_use", "id": "t1", "name": "Read", "input": {{"file_path": wrong + "/install.sh"}}}},
             {{"type": "tool_use", "id": "t2", "name": "Read", "input": {{"file_path": real + "/install.sh"}}}}]
    print(json.dumps({{"type": "assistant", "message": {{"content": calls[:1]}}}}))
    failed = os.environ.get("STUB_RESULT") != "ok"
    print(json.dumps({{"type": "user", "message": {{"content": [
        {{"type": "tool_result", "tool_use_id": "t1", "is_error": failed, "content": "File does not exist."}}]}}}}))
    print(json.dumps({{"type": "assistant", "message": {{"content": calls[1:]}}}}))
print(json.dumps({{"type": "result", "num_turns": 4, "result": pathlib.Path(os.environ["STUB_REPLY"]).read_text()}}))
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
    planned = live.RUNS * sum(case.lens == "architecture" for case in score.load_cases())
    assert f"0 already recorded, {planned} to dispatch" in capsys.readouterr().out
    assert not calls and not any(tmp.iterdir())
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


def test_the_live_run_records_each_tool_call_and_the_turn_count(tmp: Path, harness: Path, monkeypatch) -> None:
    case = case_by_id("install-prune-user-folders")
    (tmp / "reply.md").write_text(reply_for(case))
    monkeypatch.setenv("STUB_REPLY", str(tmp / "reply.md"))
    monkeypatch.setenv("STUB_MODE", "audit")
    assert live.main(["--yes-spend", "--case", case.id, "--runs", "1", "--label", "t", "--out", str(tmp / "rec"),
                      "--claude", str(harness)]) == 0
    meta = json.loads(next((tmp / "rec").rglob("run-1.meta.json")).read_text())
    assert meta["num_turns"] == 4 and meta["tainted"] == [] and meta["exit"] == 0
    assert meta["calls"] == [{"name": "Read", "path": "install.sh"}, {"name": "Grep", "pattern": "rm -rf", "path": "."},
                             {"name": "Glob", "pattern": "**/*.sh"}], "paths are relative to the case's scratch root"
    reply, meta = live.dispatch(str(tmp / "nowhere"), case, 5)
    assert {key: meta[key] for key in ("exit", "tainted", "outside_failed", "calls", "num_turns")} == {
        "exit": None, "tainted": [], "outside_failed": [], "calls": [], "num_turns": None}, "a failed start keeps it"
    assert meta["scratch"].startswith(f"reviewer-eval-{case.id}-")


def test_a_mistyped_root_path_is_outside_and_only_a_read_that_returned_something_taints(
        tmp: Path, harness: Path, monkeypatch) -> None:
    """A model that copies its random scratch suffix wrong reads a path outside the root: the check is right to call
    it outside. When that read failed, nothing was read, so the run is not tainted; a read outside that succeeded is."""
    case = case_by_id("install-prune-user-folders")
    (tmp / "reply.md").write_text(reply_for(case))
    monkeypatch.setenv("STUB_REPLY", str(tmp / "reply.md"))
    monkeypatch.setenv("STUB_MODE", "typo")
    argv = ["--yes-spend", "--case", case.id, "--runs", "1", "--label", "t", "--out", str(tmp / "rec"),
            "--claude", str(harness)]
    assert live.main(argv) == 0
    meta = json.loads(next((tmp / "rec").rglob("run-1.meta.json")).read_text())
    typo = meta["outside_failed"][0].split(" ", 1)[1]
    assert meta["tainted"] == [] and len(meta["outside_failed"]) == 1
    assert Path(typo).name == "install.sh" and Path(typo).parent.name != meta["scratch"], "the suffix differs"
    assert Path(typo).parent.name[:-1] == meta["scratch"][:-1], "only the last character of the suffix"
    assert meta["calls"][0]["error"] is True and meta["calls"][1] == {"name": "Read", "path": "install.sh"}
    monkeypatch.setenv("STUB_RESULT", "ok")
    assert live.main([*argv, "--redo"]) == 0
    meta = json.loads(next((tmp / "rec").rglob("run-1.meta.json")).read_text())
    assert len(meta["tainted"]) == 1 and meta["outside_failed"] == [], "an outside read that returned is a taint"


def test_the_live_run_stops_after_three_failures_in_a_row(tmp: Path, harness: Path, monkeypatch) -> None:
    monkeypatch.setenv("STUB_MODE", "fail")
    assert live.main(["--yes-spend", "--persona", "architecture", "--label", "t", "--out", str(tmp / "rec"),
                      "--claude", str(harness)]) == 3
    records = sorted((tmp / "rec").rglob("run-*.md"))
    assert len(records) == 3 and all("partial output" in path.read_text() for path in records)
    reply, meta = live.dispatch(str(tmp / "nowhere"), case_by_id("install-prune-user-folders"), 5)
    assert reply.startswith(live.FAILED) and meta["exit"] is None, "a harness that cannot start is a failed record"


def test_a_design_case_counts_the_approach_verdict_before_the_findings() -> None:
    """A design reply judges the whole change in its preamble (the approach verdict); a defect case never does."""
    design = next(c for c in score.load_cases() if c.match_code)
    words = " ".join(group[0].rstrip("*") for group in design.keywords)
    reply = f"Assessment: request-changes.\n\nApproach: redirect — {words}.\n\n### Findings: none\n"
    assert score.catches(reply, design)
    defect = next(c for c in score.load_cases() if not c.match_code and c.kind != "spec")
    plain = " ".join(group[0].rstrip("*") for group in defect.keywords)
    assert not score.catches(f"Assessment: request-changes — {plain}.\n\n### Findings: none\n", defect)
