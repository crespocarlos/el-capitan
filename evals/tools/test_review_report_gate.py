#!/usr/bin/env python3
"""The persisted-report gate: a report's numbered list and verdict must match its findings JSON.

`persist` appends generated sections from `--findings`, but the numbered list a reader actually acts
on is written by a model, so a finding could be dropped, re-labelled, or re-scored between the JSON
and the report. This suite pins the comparison, the legacy anchor spelling it must still accept, the
verdict mapping each mode uses, the footer, the assessment line, and the two runs that must never be
gated: one with no `--findings` and one with no `--head`.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "review" / "crew-review-findings.py"


def local_commit() -> str:
    """A commit this checkout really contains, which a non-PR `--head` must resolve to."""
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True)
    return result.stdout.strip()


def run(*args: str) -> subprocess.CompletedProcess:
    return cli(TOOL, *args)


def attention(**overrides: object) -> dict:
    """A complete emitted attention finding; overrides replace or drop a field."""
    record = {"title": "Guard missing", "label": "attention", "file": "a.ts", "line": 3,
              "disposition": "patch", "kind": "correctness", "confidence": 4,
              "verified": True, "evidence": "a.ts:3",
              "validation": "read a.ts:1-9; the guard is absent"}
    for key, value in overrides.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    return record


ASSESSMENT_PACKAGE = "## Assessment of the change\n\nthe contract section\n"
ASSESSMENT_LINE = "Assessment: request-changes — bounds the symptom, not the loop the spec measured\n"


def review_dir(tmp: Path, name: str = "ts", package: str = "in",
               out: str = "### Findings: none\n") -> Path:
    """A review directory that already satisfies the persona gate.

    `package` is what the persona was sent: the assessment gate keys on the package, not on the
    persona, so that a directory written before the rule existed still persists.
    """
    directory = tmp / "task" / "review" / name
    directory.mkdir(parents=True)
    (directory / "adversarial.in.md").write_text(package)
    (directory / "adversarial.out.md").write_text(out)
    return directory


def persist(tmp: Path, report_text: str, payload: list[dict] | None, name: str = "ts",
            *extra: str, package: str = "in", out: str = "### Findings: none\n",
            ) -> subprocess.CompletedProcess:
    """Persist one report; `payload=None` omits `--findings`, which is the un-gated run."""
    directory = review_dir(tmp, name, package, out)
    (tmp / f"report-{name}.md").write_text(report_text)
    arguments = ["persist", "--review-dir", str(directory),
                 "--report", str(tmp / f"report-{name}.md"), "--files", "a.ts",
                 "--personas", "adversarial", *extra]
    if payload is not None:
        findings = tmp / f"findings-{name}.json"
        findings.write_text(json.dumps(payload))
        arguments += ["--findings", str(findings)]
    return run(*arguments)


def failure(result: subprocess.CompletedProcess) -> str:
    """The stderr text, so a wrong rejection reads as a message rather than an assertion."""
    return f"exit {result.returncode}: {result.stdout}{result.stderr}"


def changes(entry: str, verdict: str) -> str:
    return f"## Review: changes\n\n{entry}Verdict: {verdict}\n"


def spec(entry: str, verdict: str) -> str:
    return f"## Review: Spec\n\n{entry}Verdict: {verdict}\n"


ENTRY = "1. [attention · 4] **`a.ts:3`** — Guard missing\n\n"
SPEC = ("--mode", "spec")
DATED = attention(file="evals/reports/ordering-quality-2026-11-25.md", line=9)
DEFERRED = attention(disposition="defer", verified=None, evidence=None, validation=None)
BLOCKING = attention(label="blocking", verified=True)

# (case, report, findings, extra arguments, exit code, texts stderr must carry). A rejection writes no report.
ONE = [attention()]
CONCERN = "1. [concern · 4] **`SPEC.md:12`** — Vague criterion\n\n"
TEMPLATE = "```markdown\n1. [blocking · 4] **`path/to/file.ts:42`** — one-line title\n```\n\n"
GATE = [
    ("a matching report persists", changes(ENTRY, "WARN"), ONE, (), 0, ()),
    ("a count mismatch names both counts", changes("", "PASS"), ONE, (), 2,
     ("lists 0 numbered finding(s)", "1 emitted")),
    ("a label downgrade is rejected", changes(ENTRY.replace("attention", "nit"), "PASS"), ONE, (), 2,
     ("[nit]", "[attention]")),
    ("a score mismatch is rejected", changes(ENTRY.replace("· 4", "· 5"), "WARN"), ONE, (), 2,
     ("score 5", "carries 4")),
    ("an anchor mismatch is rejected", changes(ENTRY.replace("a.ts:3", "b.ts:9"), "WARN"), ONE, (), 2,
     ("b.ts", "a.ts")),
    ("a legacy `path — line N` anchor compares equal", changes(ENTRY.replace("a.ts:3", "a.ts — line 3"), "WARN"),
     ONE, (), 0, ()),
    ("a dated filename anchor reads its line, not the year",
     changes(ENTRY.replace("a.ts:3", f"{DATED['file']}:9"), "WARN"), [DATED], (), 0, ()),
    ("an empty list with no findings passes", changes("", "PASS"), [], (), 0, ()),
    ("a deferred finding is not in the list", changes("", "PASS"), [DEFERRED], (), 0, ()),
    ("a fenced template quote is not a second entry", changes(ENTRY + TEMPLATE, "WARN"), ONE, (), 0, ()),
    ("a fenced verdict quote is not the verdict", changes(ENTRY + "```markdown\nVerdict: proceed\n```\n\n", "WARN"),
     ONE, (), 0, ()),
    ("a bold label entry is counted", changes(ENTRY.replace("[attention · 4]", "**[attention · 4]**"), "WARN"),
     ONE, (), 0, ()),
    ("a bare ordinal entry is counted", changes(ENTRY.replace("1. ", "2 "), "WARN"), ONE, (), 0, ()),
    ("a contradicting code verdict is rejected", changes(ENTRY, "PASS"), ONE, (), 2,
     ("Verdict: PASS", "derive WARN")),
    ("the last verdict line is the one compared",
     changes(ENTRY + "The earlier draft said Verdict: PASS and was wrong.\n\n", "WARN"), ONE, (), 0, ()),
    ("pass-with-nits is one word", changes(ENTRY, "pass-with-nits"), ONE, (), 2, ("Verdict: pass-with-nits",)),
    ("blocking findings derive BLOCK", changes(ENTRY.replace("attention", "blocking"), "BLOCK"), [BLOCKING], (), 0, ()),
    ("revisit with concerns passes", spec(CONCERN, "revisit"),
     [attention(label="concern", file="SPEC.md", line=12)], SPEC, 0, ()),
    ("revisit beside a clean pass is rejected", spec(CONCERN.replace("concern", "nit"), "revisit"),
     [attention(label="nit", file="SPEC.md", line=12)], SPEC, 2, ("nothing to revisit",)),
    ("proceed beside a blocking finding is rejected", spec(CONCERN.replace("concern", "blocking"), "proceed"),
     [attention(label="blocking", file="SPEC.md", line=12, verified=True)], SPEC, 2, ("has not proceeded",)),
    ("a matching spec verdict passes", spec(CONCERN, "proceed"),
     [attention(label="concern", file="SPEC.md", line=12)], SPEC, 0, ()),
    ("a code verdict in a spec mode is rejected", spec("", "PASS"), [], SPEC, 2, ("not a spec verdict",)),
    ("a head that is not a commit is rejected", changes("", "PASS"), [], ("--head", "0ec93ba"), 2,
     ("is not a commit in this repository",)),
]


@pytest.mark.parametrize("case,report,findings,extra,code,needles", GATE, ids=[row[0] for row in GATE])
def test_the_list_and_verdict_gate(case: str, report: str, findings: list[dict], extra: tuple[str, ...],
                                   code: int, needles: tuple[str, ...], tmp: Path) -> None:
    result = persist(tmp, report, findings, "ts", *extra)
    assert result.returncode == code and all(needle in result.stderr for needle in needles), failure(result)
    assert code == 0 or not (tmp / "task" / "REVIEW.md").exists(), "a rejected run writes no report"


# --- the footer -------------------------------------------------------------


def test_the_footer_closes_the_report(tmp: Path) -> None:
    """The last three lines are the decision: verdict, next step, and the reviewed commit."""
    head = local_commit()
    result = persist(tmp, changes(ENTRY, "WARN"), [attention()], "ts", "--head", head)
    assert result.returncode == 0, failure(result)
    lines = [line for line in (tmp / "task" / "REVIEW.md").read_text().splitlines() if line]
    assert lines[-3].startswith("Verdict: ") and lines[-2].startswith("> Next: "), lines[-4:]
    assert lines[-1] == f"Reviewed at: {head}", lines[-4:]


def test_a_run_without_head_omits_the_reviewed_line_and_next_overrides_the_default(tmp: Path) -> None:
    """No `--head` means no reviewed tree, so the footer claims none; a caller that knows the step passes it."""
    result = persist(tmp, changes("", "PASS"), [], "ts", "--next", "run `crew log`.")
    assert result.returncode == 0, failure(result)
    written = (tmp / "task" / "REVIEW.md").read_text()
    assert "Verdict: PASS" in written and "> Next: run `crew log`." in written, written
    assert "Reviewed at:" not in written, written


# --- the un-gated runs and the assessment line ------------------------------


def test_a_run_without_findings_is_never_rejected(tmp: Path) -> None:
    """Spec and idea reviews persist with no JSON beside them; nothing to compare is not a mismatch."""
    report = "## Review: Spec\n\n1. [concern · 4] — something vague\n\nVerdict: revise\n"
    result = persist(tmp, report, None, "spec", "--mode", "spec")
    assert result.returncode == 0, failure(result)
    assert (tmp / "task" / "REVIEW.spec.md").is_file()


NONE = "### Findings: none\n"
QUOTED = "```\nAssessment: approve | request-changes | comment — <one clause of evidence for it>\n```\n\n" + NONE
# (case, the persona's reply, the package it was sent, exit code, text stderr or the persisted report must carry)
ASSESSMENTS = [
    ("a missing assessment fails when the package asks for one", NONE, ASSESSMENT_PACKAGE, 2,
     "wrote no `Assessment:` line"),
    ("a bare assessment word fails", "Assessment: approve\n\n" + NONE, ASSESSMENT_PACKAGE, 2, "0-character clause"),
    ("a clause of exactly 20 characters passes", f"Assessment: approve — {'a' * 20}\n\n" + NONE, ASSESSMENT_PACKAGE, 0,
     "**approve** — adversarial"),
    ("a quoted template is not the persona's verdict", QUOTED, ASSESSMENT_PACKAGE, 2, "wrote no `Assessment:` line"),
    ("the report carries the lens's assessment", f"{ASSESSMENT_LINE}\n" + NONE, ASSESSMENT_PACKAGE, 0,
     "### Assessment of the change"),
    ("an overlong clause is cut with its remainder reported",
     f"Assessment: approve — {' '.join(['word'] * 300)}\n" + NONE, ASSESSMENT_PACKAGE, 0, "see `adversarial.out.md`"),
    ("a package that predates the rule is not gated", NONE, "in", 0,
     "- not asked (package predates the rule) — adversarial"),
]


@pytest.mark.parametrize("case,out,package,code,needle", ASSESSMENTS, ids=[row[0] for row in ASSESSMENTS])
def test_the_assessment_line(case: str, out: str, package: str, code: int, needle: str, tmp: Path) -> None:
    result = persist(tmp, "## Review: changes\n", [], "ts", package=package, out=out)
    written = (tmp / "task" / "REVIEW.md").read_text() if code == 0 else result.stderr
    assert result.returncode == code and needle in written, failure(result) + written


def two_lenses(tmp: Path, replies: dict[str, str]) -> str:
    directory = tmp / "task" / "review" / "lenses"
    directory.mkdir(parents=True)
    for persona, reply in replies.items():
        (directory / f"{persona}.in.md").write_text(ASSESSMENT_PACKAGE)
        (directory / f"{persona}.out.md").write_text(reply)
    report = tmp / "report-lenses.md"
    report.write_text("## Review: changes\n")
    (tmp / "findings.json").write_text("[]")
    result = run("persist", "--review-dir", str(directory), "--report", str(report), "--findings",
                 str(tmp / "findings.json"), "--files", "a.ts", "--personas", *replies)
    assert result.returncode == 0, failure(result)
    return (tmp / "task" / "REVIEW.md").read_text()


def test_each_lens_line_carries_its_own_reason(tmp: Path) -> None:
    """The tally says who agreed; these lines say why, so a reader need not open four persona files."""
    persisted = two_lenses(tmp, {
        "adversarial": "Assessment: request-changes — holdWaiting leaves detections unstamped\n" + NONE,
        "architecture": "Assessment: approve — the split into one gate is the right layer\n" + NONE})
    assert "#### Each lens, and why" in persisted and "**request-changes** — adversarial" in persisted, persisted
    assert "- **adversarial** — request-changes: holdWaiting leaves detections unstamped" in persisted
    assert "- **architecture** — approve: the split into one gate is the right layer" in persisted


def test_a_persona_that_declared_a_failure_is_not_asked_for_a_judgement(tmp: Path) -> None:
    """`pipeline.md` keeps a failed persona in `--personas`; demanding a verdict breaks that recovery."""
    persisted = two_lenses(tmp, {
        "adversarial": "Assessment: approve — the gate is wired where the package asks\n\n" + NONE,
        "code-quality": "status: truncated\nreason: harness cut the reply\nfinding: none\n"})
    assert "**approve** — adversarial" in persisted and "code-quality (truncated)" in persisted, persisted
