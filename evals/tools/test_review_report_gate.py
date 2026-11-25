#!/usr/bin/env python3
"""The persisted-report gate: a report's numbered list and verdict must match its findings JSON.

`persist` appends generated sections from `--findings`, but the numbered list a reader actually acts
on is written by a model and was checked by nothing, so a finding could be dropped, re-labelled, or
re-scored between the JSON and the report with no gate noticing. This suite pins the comparison, the
legacy anchor spelling it must still accept, the verdict mapping each mode uses, and the two runs that
must never be gated: one with no `--findings` and one with no `--head`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "review" / "crew-review-findings.py"

HEAD = "0123456789abcdef0123456789abcdef01234567"


def local_commit() -> str:
    """A commit this checkout really contains, which a non-PR `--head` must resolve to."""
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True)
    return result.stdout.strip()


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


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

    `package` is what the persona was sent, so a test that exercises the assessment gate writes the
    contract section into it: the gate keys on the package, not on the persona, so that a directory
    written before the rule existed still persists.
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


# --- the list ---------------------------------------------------------------


def test_a_matching_report_persists(tmp: Path) -> None:
    report = ("## Review: changes\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n\n"
              "Verdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 0, failure(result)


def test_a_count_mismatch_is_rejected_naming_both_counts(tmp: Path) -> None:
    """A finding dropped from the list is the failure this gate exists for."""
    report = "## Review: changes\n\nVerdict: PASS\n"
    result = persist(tmp, report, [attention()])
    assert result.returncode == 2, failure(result)
    assert "lists 0 numbered finding(s)" in result.stderr, result.stderr
    assert "1 emitted" in result.stderr, result.stderr
    assert not (tmp / "task" / "REVIEW.md").exists(), "a rejected run writes no report"


def test_a_label_mismatch_is_rejected(tmp: Path) -> None:
    """Downgrading `attention` to `nit` in the list hides a required fix from a reader."""
    report = ("## Review: changes\n\n1. [nit · 4] **`a.ts:3`** — Guard missing\n\n"
              "Verdict: PASS\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 2, failure(result)
    assert "[nit]" in result.stderr and "[attention]" in result.stderr, result.stderr


def test_a_score_mismatch_is_rejected(tmp: Path) -> None:
    report = ("## Review: changes\n\n1. [attention · 5] **`a.ts:3`** — Guard missing\n\n"
              "Verdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 2, failure(result)
    assert "score 5" in result.stderr and "carries 4" in result.stderr, result.stderr


def test_an_anchor_mismatch_is_rejected(tmp: Path) -> None:
    report = ("## Review: changes\n\n1. [attention · 4] **`b.ts:9`** — Guard missing\n\n"
              "Verdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 2, failure(result)
    assert "b.ts" in result.stderr and "a.ts" in result.stderr, result.stderr


def test_a_legacy_line_anchor_compares_equal(tmp: Path) -> None:
    """The archived reports use `path — line N`; the migration rewrites documents, not history."""
    report = ("## Review: changes\n\n1. [attention · 4] **`a.ts — line 3`** — Guard missing\n\n"
              "Verdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 0, failure(result)


def test_a_dated_filename_anchor_reads_its_line_not_the_year(tmp: Path) -> None:
    """A path may carry digits of its own: line 9 of a dated file is not line 2026.

    Taking the first digit run in the fragment made every finding against a dated filename
    unpersistable, which surfaced while reviewing a change that added one.
    """
    dated = attention(file="evals/reports/ordering-quality-2026-11-25.md", line=9)
    report = ("## Review: changes\n\n1. [attention · 4] "
              "**`evals/reports/ordering-quality-2026-11-25.md:9`** — Stale headline\n\n"
              "Verdict: WARN\n")
    result = persist(tmp, report, [dated], "dated")
    assert result.returncode == 0, failure(result)


def test_a_list_with_no_findings_passes(tmp: Path) -> None:
    """An empty review is a result, and an empty list is the honest rendering of one."""
    result = persist(tmp, "## Review: changes\n\nVerdict: PASS\n", [])
    assert result.returncode == 0, failure(result)


def test_an_empty_list_with_an_emitted_finding_fails(tmp: Path) -> None:
    result = persist(tmp, "## Review: changes\n\nVerdict: WARN\n", [attention()])
    assert result.returncode == 2, failure(result)
    assert "lists 0 numbered finding(s)" in result.stderr, result.stderr


def test_a_deferred_finding_is_not_in_the_list(tmp: Path) -> None:
    """Deferred work is appended to DEFERRED.md, so a report that omits it is not a mismatch."""
    deferred = attention(disposition="defer", verified=None, evidence=None, validation=None)
    result = persist(tmp, "## Review: changes\n\nVerdict: PASS\n", [deferred])
    assert result.returncode == 0, failure(result)


def test_a_finding_quoting_the_template_is_not_a_second_entry(tmp: Path) -> None:
    """The contract requires a verbatim fenced quote, and its own template is finding-shaped.

    Without fence awareness the quote reads as another list entry, so a correct report is rejected
    for a count mismatch it did not commit.
    """
    report = ("## Review: changes\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n\n"
              "```markdown\n1. [blocking · 4] **`path/to/file.ts:42`** — one-line title\n```\n\n"
              "Verdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 0, failure(result)


def test_a_finding_quoting_a_verdict_is_not_the_reports_verdict(tmp: Path) -> None:
    """A quote of `Verdict: proceed` in a code-mode body must not be read as the decision."""
    report = ("## Review: changes\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n\n"
              "```markdown\nVerdict: proceed\n```\n\nVerdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 0, failure(result)


def test_a_bold_label_entry_is_counted(tmp: Path) -> None:
    """`review_classify` credits `1. **[attention · 4]**`; a gate that counts fewer refuses it."""
    report = ("## Review: changes\n\n1. **[attention · 4]** **`a.ts:3`** — Guard missing\n\n"
              "Verdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 0, failure(result)


def test_a_bare_ordinal_entry_is_counted(tmp: Path) -> None:
    """`2 [attention · 4]` is a documented persona spelling, so the gate must read it too."""
    report = ("## Review: changes\n\n2 [attention · 4] **`a.ts:3`** — Guard missing\n\n"
              "Verdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 0, failure(result)


# --- the verdict ------------------------------------------------------------


def test_a_contradicting_verdict_in_a_code_mode_is_rejected(tmp: Path) -> None:
    report = ("## Review: changes\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n\n"
              "Verdict: PASS\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 2, failure(result)
    assert "Verdict: PASS" in result.stderr and "derive WARN" in result.stderr, result.stderr


def test_the_last_verdict_line_is_the_one_compared(tmp: Path) -> None:
    """A report may quote a verdict; the decision is the line it closes on."""
    report = ("## Review: changes\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n\n"
              "The earlier draft said Verdict: PASS and was wrong.\n\nVerdict: WARN\n")
    result = persist(tmp, report, [attention()])
    assert result.returncode == 0, failure(result)


def test_a_revisit_with_concerns_passes(tmp: Path) -> None:
    """`revisit` is the reviewer's word for "not ready", which a plan with concerns is.

    It maps onto the outcome the findings derive, so a concern-only review can ask for the revision
    it wants instead of claiming `proceed`; only a `revisit` beside a clean derivation is refused.
    """
    report = ("## Review: Spec\n\n1. [concern · 4] **`SPEC.md:12`** — Vague criterion\n\n"
              "Verdict: revisit\n")
    result = persist(tmp, report, [attention(label="concern", file="SPEC.md", line=12)], "spec",
                     "--mode", "spec")
    assert result.returncode == 0, failure(result)


def test_a_revisit_beside_a_clean_pass_is_rejected(tmp: Path) -> None:
    """Nothing to revisit: a plan whose findings derive PASS cannot also ask for a revision."""
    report = ("## Review: Spec\n\n1. [nit · 4] **`SPEC.md:12`** — Word choice\n\n"
              "Verdict: revisit\n")
    result = persist(tmp, report, [attention(label="nit", file="SPEC.md", line=12)], "spec",
                     "--mode", "spec")
    assert result.returncode == 2, failure(result)
    assert "nothing to revisit" in result.stderr, result.stderr


def test_a_proceed_beside_a_blocking_finding_is_rejected(tmp: Path) -> None:
    """`proceed` is only true of a plan with nothing blocking, so the one exempt case is now checked."""
    blocking = attention(label="blocking", file="SPEC.md", line=12, verified=True)
    report = ("## Review: Spec\n\n1. [blocking · 4] **`SPEC.md:12`** — Wrong approach\n\n"
              "Verdict: proceed\n")
    result = persist(tmp, report, [blocking], "spec", "--mode", "spec")
    assert result.returncode == 2, failure(result)
    assert "has not proceeded" in result.stderr, result.stderr


def test_a_matching_spec_verdict_passes(tmp: Path) -> None:
    report = ("## Review: Spec\n\n1. [concern · 4] **`SPEC.md:12`** — Vague criterion\n\n"
              "Verdict: proceed\n")
    result = persist(tmp, report, [attention(label="concern", file="SPEC.md", line=12)], "spec",
                     "--mode", "spec")
    assert result.returncode == 0, failure(result)


def test_a_code_verdict_in_a_spec_mode_is_rejected(tmp: Path) -> None:
    """One vocabulary per mode, so a spec review cannot quietly use the code scale."""
    report = "## Review: Spec\n\nVerdict: PASS\n"
    result = persist(tmp, report, [], "spec", "--mode", "spec")
    assert result.returncode == 2, failure(result)
    assert "not a spec verdict" in result.stderr, result.stderr


def test_blocking_findings_derive_block(tmp: Path) -> None:
    blocking = attention(label="blocking", verified=True)
    report = ("## Review: changes\n\n1. [blocking · 4] **`a.ts:3`** — Guard missing\n\n"
              "Verdict: BLOCK\n")
    assert persist(tmp, report, [blocking]).returncode == 0, "a matching BLOCK must persist"


# --- the footer -------------------------------------------------------------


def test_the_footer_closes_the_report(tmp: Path) -> None:
    """The last three lines are the decision: verdict, next step, and the reviewed commit."""
    report = ("## Review: changes\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n\n"
              "Verdict: WARN\n")
    head = local_commit()
    result = persist(tmp, report, [attention()], "ts", "--head", head)
    assert result.returncode == 0, failure(result)
    lines = [line for line in (tmp / "task" / "REVIEW.md").read_text().splitlines() if line]
    assert lines[-3].startswith("Verdict: "), lines[-4:]
    assert lines[-2].startswith("> Next: "), lines[-4:]
    assert lines[-1] == f"Reviewed at: {head}", lines[-4:]


def test_a_head_that_is_not_a_commit_is_rejected(tmp: Path) -> None:
    """The SHA check survives the footer move: it validates where the value enters, not where it lands."""
    result = persist(tmp, "## Review: changes\n\nVerdict: PASS\n", [], "ts", "--head", "0ec93ba")
    assert result.returncode == 2, failure(result)
    assert "is not a commit in this repository" in result.stderr, result.stderr
    assert not (tmp / "task" / "REVIEW.md").exists()


def test_a_run_without_head_omits_the_reviewed_line(tmp: Path) -> None:
    """No `--head` means no reviewed tree, so the footer claims none rather than an empty one."""
    report = "## Review: changes\n\nVerdict: PASS\n"
    result = persist(tmp, report, [])
    assert result.returncode == 0, failure(result)
    written = (tmp / "task" / "REVIEW.md").read_text()
    assert "Verdict: PASS" in written, written
    assert "> Next: " in written, written
    assert "Reviewed at:" not in written, written


def test_next_overrides_the_mode_default(tmp: Path) -> None:
    """One code path: a caller that knows the step passes it instead of a second renderer."""
    result = persist(tmp, "## Review: changes\n\nVerdict: PASS\n", [], "ts", "--next", "run `crew log`.")
    assert result.returncode == 0, failure(result)
    assert "> Next: run `crew log`." in (tmp / "task" / "REVIEW.md").read_text()


# --- the un-gated runs ------------------------------------------------------


def test_a_run_without_findings_is_never_rejected(tmp: Path) -> None:
    """Spec and idea reviews persist with no JSON beside them; nothing to compare is not a mismatch."""
    report = "## Review: Spec\n\n1. [concern · 4] — something vague\n\nVerdict: revise\n"
    result = persist(tmp, report, None, "spec", "--mode", "spec")
    assert result.returncode == 0, failure(result)
    assert (tmp / "task" / "REVIEW.spec.md").is_file()


def test_a_missing_assessment_fails_when_the_package_asks_for_one(tmp: Path) -> None:
    """The persona judged the lines and not the change; the review is incomplete."""
    report = "## Review: changes\n\n### Files reviewed\n"
    result = persist(tmp, report, [], "noassess", package=ASSESSMENT_PACKAGE)
    assert result.returncode == 2, failure(result)
    assert "wrote no `Assessment:` line" in result.stderr, result.stderr


def test_a_bare_assessment_word_fails(tmp: Path) -> None:
    """An opinion with nothing behind it is what the line exists to replace."""
    result = persist(tmp, "## Review: changes\n", [], "bare",
                     package=ASSESSMENT_PACKAGE, out="Assessment: approve\n\n### Findings: none\n")
    assert result.returncode == 2, failure(result)
    assert "0-character clause" in result.stderr and "at least 20" in result.stderr, result.stderr


def test_an_assessment_clause_at_the_floor_passes(tmp: Path) -> None:
    """The floor is `< 20`, so a clause of exactly 20 characters is accepted; `<` vs `<=` is pinned."""
    clause = "a" * 20
    result = persist(tmp, "## Review: changes\n", [], "floor",
                     package=ASSESSMENT_PACKAGE,
                     out=f"Assessment: approve — {clause}\n\n### Findings: none\n")
    assert result.returncode == 0, failure(result)


def test_a_quoted_assessment_template_is_not_the_personas_verdict(tmp: Path) -> None:
    """The contract shows the line in a fence; echoing it must not satisfy the gate as `approve`."""
    quoted = ("```\nAssessment: approve | request-changes | comment — "
              "<one clause of evidence for it>\n```\n\n### Findings: none\n")
    result = persist(tmp, "## Review: changes\n", [], "quoted",
                     package=ASSESSMENT_PACKAGE, out=quoted)
    assert result.returncode == 2, failure(result)
    assert "wrote no `Assessment:` line" in result.stderr, result.stderr


def test_the_report_carries_the_lenses_assessment(tmp: Path) -> None:
    """The reader must see the judgement without opening five persona files."""
    result = persist(tmp, "## Review: changes\n", [], "rated",
                     package=ASSESSMENT_PACKAGE,
                     out=f"{ASSESSMENT_LINE}\n### Findings: none\n")
    assert result.returncode == 0, failure(result)
    persisted = (tmp / "task" / "REVIEW.md").read_text()
    assert "### Assessment of the change" in persisted, persisted
    assert "**request-changes** — adversarial" in persisted, persisted


def test_each_lens_line_carries_its_own_reason(tmp: Path) -> None:
    """The tally says who agreed; these lines say why, so a reader need not open four persona files."""
    directory = tmp / "task" / "review" / "reasons"
    directory.mkdir(parents=True)
    words = {"adversarial": ("request-changes", "holdWaiting leaves detections unstamped"),
             "architecture": ("approve", "the split into one gate is the right layer")}
    for persona, (word, clause) in words.items():
        (directory / f"{persona}.in.md").write_text(ASSESSMENT_PACKAGE)
        (directory / f"{persona}.out.md").write_text(
            f"Assessment: {word} — {clause}\n### Findings: none\n")
    report = tmp / "report-reasons.md"
    report.write_text("## Review: changes\n")
    result = run("persist", "--review-dir", str(directory), "--report", str(report),
                 "--files", "a.ts", "--personas", "adversarial", "architecture")
    assert result.returncode == 0, failure(result)
    persisted = (tmp / "task" / "REVIEW.md").read_text()
    assert "#### Each lens, and why" in persisted, persisted
    assert "- **adversarial** — request-changes: holdWaiting leaves detections unstamped" in persisted
    assert "- **architecture** — approve: the split into one gate is the right layer" in persisted


def test_an_overlong_clause_is_cut_with_its_remainder_reported(tmp: Path) -> None:
    """A reason that ends mid-sentence must say so, or it reads as the whole of what the lens wrote."""
    long_clause = " ".join(["word"] * 300)
    result = persist(tmp, "## Review: changes\n", [], "long",
                     package=ASSESSMENT_PACKAGE,
                     out=f"Assessment: approve — {long_clause}\n### Findings: none\n")
    assert result.returncode == 0, failure(result)
    persisted = (tmp / "task" / "REVIEW.md").read_text()
    assert "… (+" in persisted and "see `adversarial.out.md`" in persisted, persisted


def test_a_package_that_predates_the_rule_is_not_gated(tmp: Path) -> None:
    """Archived reviews must persist: the rule applies where the package asked, not retroactively."""
    result = persist(tmp, "## Review: changes\n", [], "legacy")
    assert result.returncode == 0, failure(result)
    persisted = (tmp / "task" / "REVIEW.md").read_text()
    assert "- not asked (package predates the rule) — adversarial" in persisted, persisted


def test_a_persona_that_declared_a_failure_is_not_asked_for_a_judgement(tmp: Path) -> None:
    """`pipeline.md` keeps a failed persona in `--personas`; demanding a verdict breaks that recovery."""
    directory = tmp / "task" / "review" / "failed"
    directory.mkdir(parents=True)
    (directory / "adversarial.in.md").write_text(ASSESSMENT_PACKAGE)
    (directory / "adversarial.out.md").write_text(
        "Assessment: approve — the gate is wired where the package asks\n\n### Findings: none\n")
    (directory / "code-quality.in.md").write_text(ASSESSMENT_PACKAGE)
    (directory / "code-quality.out.md").write_text(
        "status: truncated\nreason: harness cut the reply\nfinding: none\n")
    report = tmp / "report-failed.md"
    report.write_text("## Review: changes\n")
    result = run("persist", "--review-dir", str(directory), "--report", str(report),
                 "--files", "a.ts", "--personas", "adversarial", "code-quality")
    assert result.returncode == 0, failure(result)
    persisted = (tmp / "task" / "REVIEW.md").read_text()
    assert "**approve** — adversarial" in persisted, persisted
    assert "code-quality (truncated)" in persisted, persisted


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
