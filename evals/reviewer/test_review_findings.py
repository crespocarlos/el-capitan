#!/usr/bin/env python3
"""`crew-review-findings.py`: normalize, persist and their evidence gates, coverage, outcomes, probes, review-dir.

Every subcommand runs in this process through `evals/tools/cli_runner.py`; the reply-capture hook runs under bash.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from cli_runner import launcher
from cli_runner import run as cli
from harness_hook import run as hook

TOOL = Path(__file__).resolve().parents[2] / "src" / "crew" / "review" / "crew_review_findings.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return cli(TOOL, *args)


def no_findings(tmp: Path) -> str:
    """An empty findings file: `persist` in self and changes mode requires `--findings`."""
    path = tmp / "no-findings.json"
    path.write_text("[]")
    return str(path)


def write_map(tmp: Path, known: list[str], mapping: list) -> tuple[Path, Path]:
    """Write a hunk index and a layer map, so coverage can be exercised without a real diff."""
    hunks = tmp / "hunks.json"
    hunks.write_text(json.dumps({"files": [], "hunks": [{"id": hunk_id} for hunk_id in known]}))
    layers = tmp / "layers.json"
    layers.write_text(json.dumps({"layers": [
        {"id": f"L{index}", "explainer": "why", "reviewFocus": "- verify", "hunks": assigned}
        for index, assigned in enumerate(mapping, 1)
    ]}))
    return hunks, layers


def test_normalize_canonicalizes_and_merges_duplicate_personas(tmp: Path) -> None:
    source = tmp / "candidates.json"
    source.write_text(json.dumps([
        {"title": "Missing null guard", "label": "Blocking", "file": "a.ts", "persona": "Reviewer-Adversarial"},
        {"title": "  missing NULL   guard ", "label": "blocking", "file": "a.ts", "persona": "Code Quality"},
    ]))
    result = run("normalize", str(source))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["persona"] == ["adversarial", "code-quality"]
    assert len(payload["duplicates"]) == 1


def test_normalize_keeps_the_excerpt_and_comment_a_second_lens_supplied(tmp: Path) -> None:
    """Two lenses flagging one defect must not lose the excerpt or comment either supplied."""
    source = tmp / "candidates.json"
    source.write_text(json.dumps([
        {"title": "Missing null guard", "label": "blocking", "kind": "correctness", "file": "a.ts",
         "line": 3, "persona": "adversarial", "disposition": "patch", "verified": True,
         "confidence": 4, "evidence": "a.ts:3@abc1234",
         "validation": "read the caller and confirmed the guard is absent"},
        {"title": "  missing NULL   guard ", "label": "blocking", "kind": "correctness",
         "file": "a.ts", "line": 3, "persona": "code-quality", "disposition": "patch",
         "verified": True, "confidence": 3, "evidence": "a.ts:3@abc1234",
         "excerpt": "const value = row.data;\nvalue.length;",
         "validation": "read the same call site",
         "comment": "Could this read hit a row with no data?"},
    ]))
    result = run("normalize", str(source))
    assert result.returncode == 0, result.stderr
    merged = json.loads(result.stdout)["findings"][0]
    assert merged["excerpt"].startswith("const value"), merged
    assert merged["comment"] == "Could this read hit a row with no data?", merged
    assert merged["persona"] == ["adversarial", "code-quality"], merged


def test_normalize_rejects_unknown_persona(tmp: Path) -> None:
    source = tmp / "bad.json"
    source.write_text(json.dumps([{"title": "x", "label": "nit", "persona": "nobody"}]))
    result = run("normalize", str(source))
    assert result.returncode == 2
    assert "unknown persona" in result.stderr


def test_normalize_accepts_legacy_persona(tmp: Path) -> None:
    """Old review directories name the removed `fresh-eyes` persona and must still normalize."""
    source = tmp / "legacy.json"
    source.write_text(json.dumps([{"title": "x", "label": "nit", "persona": "Fresh Eyes"}]))
    result = run("normalize", str(source), "--lenient")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["findings"][0]["persona"] == ["fresh-eyes"]


def test_normalize_rejects_an_empty_persona_list(tmp: Path) -> None:
    """An empty list is a caller that meant to attribute the finding and did not.

    Absence stays legal, because a record written before personas were recorded has to remain
    re-readable; an explicit `[]` is not legacy data, and letting it through creates the
    unattributed bucket that no precision figure can account for.
    """
    source = tmp / "empty.json"
    source.write_text(json.dumps([
        {"title": "x", "label": "nit", "persona": [], "kind": "other", "confidence": 3,
         "disposition": "patch"}]))
    result = run("normalize", str(source))
    assert result.returncode == 2 and "names no persona" in result.stderr, result.stderr
    source.write_text(json.dumps([
        {"title": "x", "label": "nit", "kind": "other", "confidence": 3, "disposition": "patch"}]))
    assert run("normalize", str(source)).returncode == 0, "an absent key is still readable"


def test_persist_writes_both_reports_and_appends_deferred(tmp: Path) -> None:
    task = tmp / "task"
    review_dir = task / "review" / "2026-10-30T12-00"
    report = tmp / "report.md"
    # The report lists its one emitted finding; the deferred one is appended from JSON and is not
    # part of the numbered list a reader acts on. The gate compares the two in order.
    report.write_text("## Verdict: PASS\n\n1. [nit · 5] — Rename var\n")
    findings = tmp / "findings.json"
    findings.write_text(json.dumps([
        {"title": "Old flaky helper", "label": "attention", "file": "b.ts", "line": 4,
         "disposition": "defer", "kind": "reliability", "confidence": 4},
        {"title": "Rename var", "label": "nit", "disposition": "patch", "kind": "other",
         "confidence": 5},
    ]))
    # Persistence always names its personas and proves each one ran; a report with no
    # persona evidence is indistinguishable from a full review that skipped a lens.
    for persona in ("adversarial", "code-quality"):
        (review_dir / f"{persona}.in.md").parent.mkdir(parents=True, exist_ok=True)
        (review_dir / f"{persona}.in.md").write_text("in")
        (review_dir / f"{persona}.out.md").write_text("### Findings: none\n")
    for _ in range(2):
        result = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                     "--findings", str(findings), "--files", "b.ts",
                     "--personas", "adversarial", "code-quality")
        assert result.returncode == 0, result.stderr
    for path in (review_dir / "REVIEW.md", task / "REVIEW.md"):
        text = path.read_text()
        assert text.startswith("## Verdict: PASS")
        assert "### Files reviewed\n- `b.ts`" in text
    deferred = (task / "DEFERRED.md").read_text().splitlines()
    assert len(deferred) == 1 and all("Old flaky helper — `b.ts:4`" in line for line in deferred)
    assert json.loads(result.stdout)["deferred"] == 1


def test_persist_rejects_unexpected_review_dir(tmp: Path) -> None:
    report = tmp / "report.md"
    report.write_text("x\n")
    result = run("persist", "--review-dir", str(tmp / "task" / "other" / "ts"), "--report", str(report))
    assert result.returncode == 2
    assert not (tmp / "task" / "REVIEW.md").exists()


def test_normalize_requires_verified_evidence_by_default(tmp: Path) -> None:
    """The gates are the default; `--lenient` is the documented escape.

    The 2026-11-22 flip: `--strict` used to be the only way to reach these checks, and 84 recorded
    reviews omitted it, leaving 464 `verified: true` findings with no validation sentence. So the
    no-flag call is now the gated one, and `--strict` survives one cycle as a no-op alias.
    """
    source = tmp / "c.json"
    base = {"title": "t", "label": "attention", "file": "a.ts", "disposition": "patch",
            "kind": "correctness", "confidence": 3}
    source.write_text(json.dumps([base]))
    assert run("normalize", str(source)).returncode == 2
    assert run("normalize", str(source), "--strict").returncode == 2
    assert run("normalize", str(source), "--lenient").returncode == 0
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3",
                                   "validation": "read a.ts:1-9; the guard is absent"}]))
    assert run("normalize", str(source)).returncode == 0
    # `verified: true` claims a second read; the gate requires its conclusion too, so a bare
    # boolean cannot pass as evidence of one.
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3"}]))
    gated = run("normalize", str(source))
    assert gated.returncode == 2 and "validation sentence" in gated.stderr
    # `--lenient` still normalizes, because older artifacts have no such field.
    assert run("normalize", str(source), "--lenient").returncode == 0
    for evidence in (True, {}, "verified elsewhere", "a.ts"):
        source.write_text(json.dumps([{**base, "verified": True, "evidence": evidence,
                                       "validation": "read it"}]))
        assert run("normalize", str(source)).returncode == 2
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3@abc1234",
                                   "validation": "read it at the PR head"}]))
    # A PR-head finding cannot be re-read from the checkout, so the record must carry the lines it
    # verified: `path:line@sha` alone needs the network and a session that still has access.
    head_gated = run("normalize", str(source))
    assert head_gated.returncode == 2 and "records no excerpt" in head_gated.stderr, head_gated.stderr
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3@abc1234",
                                   "validation": "read it at the PR head",
                                   "excerpt": "const guard = false;"}]))
    assert run("normalize", str(source)).returncode == 0
    # A working-tree finding is re-readable from the checkout, so it needs no stored copy.
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3",
                                   "validation": "read a.ts:1-9"}]))
    assert run("normalize", str(source)).returncode == 0
    many = [{**base, "title": f"t{i}", "label": "nit"} for i in range(8)]
    source.write_text(json.dumps(many))
    result = run("normalize", str(source))
    assert result.returncode == 2 and "cap" in result.stderr


def test_normalize_caps_nits_separately_from_total(tmp: Path) -> None:
    source = tmp / "c.json"
    ok = {"verified": True, "evidence": "a.ts:3", "file": "a.ts", "disposition": "patch",
          "validation": "read a.ts:1-9", "kind": "correctness", "confidence": 3}

    def write(items: list[dict]) -> subprocess.CompletedProcess:
        source.write_text(json.dumps(items))
        return run("normalize", str(source))

    # Nits are capped on their own: even one nit over budget fails while the severity findings are
    # far under their cap. This is the regression the tiering exists to prevent, so polish cannot
    # evict severity.
    result = write([{**ok, "title": "only", "label": "blocking"}]
                   + [{**ok, "title": f"nit {i}", "label": "nit"} for i in range(5)])
    assert result.returncode == 2 and "cap of 4" in result.stderr

    # The budgets are independent, so both maxima can be reached at once: 12 severity findings plus
    # the 4-nits allowance, which is also the largest nit count any recorded review emitted.
    full = [{**ok, "title": f"a {i}", "label": "attention"} for i in range(12)]
    full += [{**ok, "title": f"nit {i}", "label": "nit"} for i in range(4)]
    assert write(full).returncode == 0

    # One more severity finding exceeds the non-nit cap, and the message names the constant so the
    # cap and this test cannot drift apart silently.
    result = write(full + [{**ok, "title": "a 12", "label": "attention"}])
    assert result.returncode == 2 and "cap of 12" in result.stderr

    # Dropping a nit to make room for a severity finding is accepted: the nit budget bounds polish,
    # never severity.
    assert write(full[:12] + full[13:]).returncode == 0


def test_persist_strict_allows_a_nit_with_no_evidence(tmp: Path) -> None:
    """Step 2 requires `verified` + `evidence` of emitted blocking/attention only, so a nit may carry
    none — and the `--files` gate must not dereference a missing location.

    2026-11-18: every emitted finding went through that gate, which called `evidence.split("@")`
    unconditionally. A nit with no evidence raised AttributeError instead of persisting, and the
    traceback made it look as though strict mode *required* evidence on nits.
    """
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report = tmp / "report.md"
    report.write_text("## Verdict: PASS\n\n1. [nit · 5] — An unanchored nit\n")
    findings = tmp / "findings.json"
    findings.write_text(json.dumps([
        {"title": "An unanchored nit", "label": "nit", "disposition": "patch", "kind": "other",
         "confidence": 5},
    ]))
    # `persist` prints no per-finding output and writes no findings file, so retention is proved at
    # `normalize`, which is the stage that hands `persist` its list.
    consolidated = tmp / "consolidation.json"
    normalized = run("normalize", str(findings), "--output", str(consolidated))
    assert normalized.returncode == 0, normalized.stderr
    assert [f["title"] for f in json.loads(consolidated.read_text())["findings"]] == ["An unanchored nit"]
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                 "--findings", str(consolidated), "--mode", "changes", "--files", "a.ts",
                 "--personas", "adversarial", "--strict")
    assert result.returncode == 0, result.stderr
    assert (review_dir / "REVIEW.md").is_file()

    def persist_with(extra: dict) -> subprocess.CompletedProcess:
        findings.write_text(json.dumps([{"title": "probe", "label": "nit", "disposition": "patch",
                                         "kind": "other", "confidence": 5, **extra}]))
        return run("persist", "--review-dir", str(review_dir), "--report", str(report),
                   "--findings", str(findings), "--mode", "changes", "--files", "a.ts",
                   "--personas", "adversarial", "--strict")

    # A nit that does cite a location still has to cite one under review.
    result = persist_with({"evidence": "other.ts:4"})
    assert result.returncode == 2 and "not in the reviewed file set" in result.stderr, result.stderr
    # A malformed evidence value is a caller bug, not an absent location — reject it, do not skip it.
    for malformed in (True, {}, 7):
        result = persist_with({"evidence": malformed})
        assert result.returncode == 2 and "evidence must be a string" in result.stderr, (
            f"{malformed!r}: {result.stderr}"
        )
    # The severity rule still binds at this call site: an unverified attention finding fails here.
    findings.write_text(json.dumps([
        {"title": "An unverified attention finding", "label": "attention", "disposition": "patch",
         "kind": "correctness", "confidence": 4},
    ]))
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                 "--findings", str(findings), "--mode", "changes", "--files", "a.ts",
                 "--personas", "adversarial", "--strict")
    assert result.returncode == 2 and "unverified attention finding" in result.stderr, result.stderr


def test_persist_rejects_a_report_carrying_a_generated_section(tmp: Path) -> None:
    """`persist` appends `### Coverage by layer` and `### Files reviewed`, so a report that already
    carries one would render it twice — the second copy indistinguishable from the first.

    2026-11-18: two consecutive reviews hand-wrote both sections into `report.md`, and each REVIEW.md
    carried the coverage table and the file list twice.
    """
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report = tmp / "report.md"

    def persist(listed: list | None = None) -> subprocess.CompletedProcess:
        (tmp / "findings.json").write_text(json.dumps(listed or []))
        return run("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", str(tmp / "findings.json"),
                   "--mode", "changes", "--files", "a.ts", "--personas", "adversarial")

    for heading in ("### Coverage by layer", "### Files reviewed"):
        report.write_text(f"## Review: changes\n\n{heading}\n- something\n")
        result = persist()
        assert result.returncode == 2, f"{heading}: {result.stdout}"
        assert heading in result.stderr and "delete it from the report" in result.stderr, result.stderr
        assert not (tmp / "task" / "REVIEW.md").exists(), f"{heading} persisted anyway"

    # A finding may quote a heading verbatim (the contract requires quoting) — that is not a
    # duplicate section. Verified against the 2026-11-18 report that quoted one inside a fence.
    report.write_text(
        "## Review: changes\n\n1. [nit · 4] **a.md — line 2** — the doc says\n\n"
        "```text\n### Files reviewed\n- a.ts\n```\n"
    )
    quoted = [{"title": "the doc says", "label": "nit", "file": "a.md", "line": 2, "disposition": "patch",
               "kind": "documentation", "confidence": 4}]
    assert persist(quoted).returncode == 0, "a quoted heading was rejected as a duplicate section"
    # A deeper heading is a different section: `#### Files reviewed` is not `### Files reviewed`.
    report.write_text("## Review: changes\n\n#### Files reviewed by hand\n")
    assert persist().returncode == 0, "a level-4 heading was rejected as a duplicate section"

    # A clean report still persists, and persist supplies both sections itself.
    report.write_text("## Review: changes\n")
    result = persist()
    assert result.returncode == 0, result.stderr
    text = (tmp / "task" / "REVIEW.md").read_text()
    assert text.count("### Files reviewed") == 1, text
    assert "### Coverage by layer" not in text  # no layer map, so nothing generated


def test_persist_strict_requires_persona_artifacts(tmp: Path) -> None:
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    report = tmp / "report.md"
    report.write_text("x\n")
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", no_findings(tmp), "--strict", "--personas", "adversarial")
    result = run(*args)
    assert result.returncode == 2 and "adversarial.in.md" in result.stderr
    (review_dir / "adversarial.in.md").write_text("in")
    # A real persona artifact carries a verdict or a status line; a bare word with
    # neither is indistinguishable from a crashed run and must not pass the gate.
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    assert run(*args).returncode == 0
    comma_args = (
        "persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", no_findings(tmp),
        "--strict", "--personas", "adversarial,code-quality",
    )
    result = run(*comma_args)
    assert result.returncode == 2 and "comma-separated personas" in result.stderr


def test_persist_strict_rejects_placeholder_persona_output(tmp: Path) -> None:
    """A stub with a plausible status word, like an empty reply (see `persona_outcome`), must not pass as a completed persona."""
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    report = tmp / "report.md"
    report.write_text("x\n")
    for persona, body in {
        "adversarial": "### Findings: none\n",
        "code-quality": "# code-quality raw response captured\nstatus: dispatched\n",
    }.items():
        (review_dir / f"{persona}.in.md").write_text("in")
        (review_dir / f"{persona}.out.md").write_text(body)
    gated = ("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", no_findings(tmp), "--strict")
    result = run(*gated, "--personas", "adversarial", "code-quality")
    assert result.returncode == 2 and "no output" in result.stderr, result.stdout + result.stderr
    assert not (tmp / "task" / "REVIEW.md").exists()
    # The same placeholder alone must fail too, and a real artifact must still pass.
    (review_dir / "adversarial.out.md").write_text("status: dispatched\n")
    assert run(*gated, "--personas", "adversarial").returncode == 2
    for persona in ("adversarial", "code-quality"):
        (review_dir / f"{persona}.out.md").write_text("### Findings: none\n")
    assert run(*gated, "--personas", "adversarial", "code-quality").returncode == 0


def test_mode_argument_accepts_documented_casing(tmp: Path) -> None:
    """`--mode PR` must select, not fail on argparse before any persona is dispatched.

    2026-11-04 PR #302200: `select --mode PR` exited with `invalid choice: 'PR'` while the
    protocol names the mode `PR`. Rejecting the documented spelling wastes a review run.
    """
    for mode in ("PR", "pr", "PR auto", "self auto-loop", "CHANGES"):
        result = run("select", "--mode", mode, "--paths", "README.md")
        assert result.returncode == 0, f"{mode}: {result.stdout}{result.stderr}"
        assert json.loads(result.stdout), f"{mode} selected no persona"
    invalid = run("select", "--mode", "bogus", "--paths", "README.md")
    assert invalid.returncode != 0 and "invalid choice" in invalid.stderr


def test_labeled_finding_accepts_every_shape_personas_write(tmp: Path) -> None:
    """A complete finding must pass whatever order a persona put the label and anchor in.

    2026-11-16: personas wrote `1. **[attention]** path:42` and `` `path:42` — [attention] ``;
    both carried real findings yet `persist --strict` called them placeholders and aborted the
    whole review. Only shapes without a real `path:line` anchor stay rejected.
    """
    spec = importlib.util.spec_from_file_location(
        "review_findings_mod", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    labeled = module.LABELED_FINDING

    accepted = [
        "[attention] src/a.ts:42 — missing guard",              # mandated, label first
        "1. [blocking] **`file.ts` — line 42** — title",         # persona output_format
        "1. **[attention]** src/a.ts:42 — missing guard",        # label inside leading bold
        "1. **[attention] src/a.ts:42 — missing guard**",        # label and anchor both bold
        "1. `src/a.ts:42` — [attention] missing guard",          # anchor before label
        "2. [nit] src/b.tsx:7 tweak",                            # numbered, no bold
        "3. [needs more info] src/c.ts:9 — stakes?",             # multi-word severity
        # The scored label the contract mandates must classify, or `persist` refuses every
        # artifact a persona writes under the current format.
        "1. [attention · 4] **`a.ts — line 3`** — missing guard",
        "2. [blocking · 5] src/a.ts:42 — the guard never runs",
        "1. `src/a.ts:42` — [attention · 3] missing guard",
        "- **[attention · 2]** src/a.ts:12 drops the timeout",
    ]
    for text in accepted:
        assert labeled.search(text), f"rejected a real finding: {text!r}"

    rejected = [
        "[attention] missing guard",                             # no anchor
        "[attention] src/a.ts — missing guard",                  # path, no line
        "1. [major] src/a.ts:42 — unknown severity",             # not a severity label
        "The code is [attention] but fine src/a.ts:42",          # label not line-leading
        "raw response captured",                                 # placeholder
        "status: dispatched",                                    # marker only
    ]
    for text in rejected:
        assert not labeled.search(text), f"accepted a non-finding: {text!r}"


def test_persist_pr_mode_accepts_head_absent_from_local_repo(tmp: Path) -> None:
    """A PR review records the GitHub head SHA, which the local checkout never fetches."""
    task = tmp / "task"
    review_dir = task / "review" / "ts"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report = tmp / "report.md"
    report.write_text("## Review: PR\n")
    absent = "0123456789abcdef0123456789abcdef01234567"
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report),
            "--mode", "pr", "--head", absent, "--personas", "adversarial")
    result = run(*args)
    assert result.returncode == 0, result.stderr
    assert f"Reviewed at: {absent}" in (task / "REVIEW.md").read_text()
    # Non-PR modes still reject a SHA the local repository cannot resolve.
    local = run("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", no_findings(tmp),
                "--mode", "self", "--head", absent, "--personas", "adversarial")
    assert local.returncode == 2 and "is not a commit" in local.stderr


def test_persist_pr_mode_requires_a_head_sha(tmp: Path) -> None:
    review_dir = tmp / "review-root" / "review" / "ts"
    review_dir.mkdir(parents=True)
    report = tmp / "report.md"
    report.write_text("## Review: PR\n")
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report), "--mode", "pr",
                 "--personas", "adversarial")
    assert result.returncode == 2 and "requires --head" in result.stderr
    assert not (review_dir / "REVIEW.md").exists()


def test_persist_pr_mode_rejects_task_dir(tmp: Path) -> None:
    """A PR review must never overwrite a task's authoritative REVIEW.md."""
    task = tmp / "task"
    (task / "review" / "ts").mkdir(parents=True)
    (task / "SPEC.md").write_text("# T\n\n## Status\nIMPLEMENTING\n")
    report = tmp / "report.md"
    report.write_text("## Review: PR\n")
    result = run("persist", "--review-dir", str(task / "review" / "ts"), "--report", str(report),
                 "--mode", "pr", "--head", "0123456789abcdef0123456789abcdef01234567",
                 "--personas", "adversarial")
    assert result.returncode == 2 and "outside task state" in result.stderr
    assert not (task / "REVIEW.md").exists()


def test_persona_outcome_accepts_every_documented_persona_format(tmp: Path) -> None:
    """Every real persona response must classify as `ok`, or `--strict` discards the run.

    The regression this guards: `persona_outcome` once accepted only a verdict line or a
    numbered `N. [blocking]` finding, so the unnumbered formats documented by
    reviewer-code-quality, reviewer-product-flow, reviewer-prompt-quality, and
    reviewer-explorer all classified as `unknown` -- and a stricter coverage gate then
    refused genuinely complete reviews.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("review_findings", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    accepted = {
        # reviewer-adversarial / reviewer-architecture: numbered, labeled
        "numbered": "1. [blocking] **`file.ts` — line 12** — title\n",
        # reviewer-code-quality / reviewer-product-flow: anchored, unnumbered, unlabeled
        "anchored": "**`src/a.ts` — line 42** — missing null guard\n\nFix/Response: add a guard.\n",
        # reviewer-prompt-quality standalone: concept anchor, no file line
        "concept": "**Ownership** — two documents claim one rule\n\nFix/Response: drop one.\n",
        # reviewer-explorer: fixed section set, no findings list
        "explorer": "## Similar patterns\n- `src/b.ts` (lines 10-18) — same retry loop\n",
        # every persona: the emptiness sentinel, which no longer borrows the word `Verdict:`
        "sentinel": "### Findings: none\n",
        # bullet-style findings: 5 recorded reviews used `- [label]` and were refused as placeholders
        "bulleted": "- [blocking] src/a.ts:47 leaves the retry loop unbounded\n",
        "bulleted_bold": "- **[attention]** src/a.ts:12 drops the timeout\n",
        # an `Anchor:` line carries the location outside the label's line
        "anchor_line": (
            "[attention] Missing regression coverage for a manage-without-configure user.\n"
            "Anchor: public/sources/sources_table.tsx:162-164@be06db4\n"
        ),
        # a spec review quotes the sentence it attacks instead of citing a diff path
        "spec_quote": (
            "1. [blocking] **Separate path still fires in the exact case the spec fixes**\n"
            "   Spec anchors: Breach \"continues the candidate unless the pair is a Separate path\".\n"
        ),
        # a spec review whose finding carries only a line number against the one artifact. Text is the
        # real 2026-11-04 record: `611 (570-571, 328-329, 606): unscoped example says …`.
        "spec_line_only": (
            "2 [blocking] 611 (570-571, 328-329, 606): unscoped example says \"not measured: share, "
            "attempts per day\", contradicting the rule that a non-applicable figure is left out\n"
        ),
    }
    rejected = {
        "dispatched": "# raw response captured\nstatus: dispatched\n",
        "summary_only": "Findings delivered above, see next.\n",
        "frontmatter_only": "---\npersona: code-quality\ndispatched: yes\n---\n# raw response captured\n",
        "verdict_marker_only": "### Verdict:\n",
        "severity_marker_only": "[nit]\n",
        "unanchored_label": "[nit] rename this\n",
        "fix_marker_only": "Fix/Response:\n",
        "explorer_header_only": "## Similar patterns\n",
        "out_of_scale_score": "1. [attention · 6] **`a.ts — line 3`** — guard missing\n",
        "empty": "",
    }
    # An orchestrator digest is not the persona's response, so it gets its own outcome rather than
    # being reported as "no output". All five wordings come from the 57 recorded artifacts.
    summarised = {
        "paren": "(condensed) 1 [blocking] a.ts:1 breaks\n",
        "relay_header": "# adversarial output (condensed relay)\n1 [blocking] a.ts:1 breaks\n",
        "record": "Condensed record of the persona response (13 findings).\n1 [blocking] a.ts:1 breaks\n",
        "status_complete": "status: complete (condensed; the full raw report is in the session transcript)\n",
        "status_ok": "status: ok (condensed)\nverdict: revisit\n",
    }
    for name, body in accepted.items():
        path = tmp / f"{name}.out.md"
        path.write_text(body)
        assert module.persona_outcome(path) == "ok", name
    for name, body in summarised.items():
        path = tmp / f"{name}.out.md"
        path.write_text(body)
        assert module.persona_outcome(path) == "summarized", name
    for name, body in rejected.items():
        path = tmp / f"{name}.out.md"
        path.write_text(body)
        assert module.persona_outcome(path) == "unknown", name


def test_canonical_personas_rejects_comma_string_without_split(tmp: Path) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("review_findings", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.canonical_personas("adversarial,code-quality", split_commas=False)
    except ValueError as error:
        assert "comma-separated personas" in str(error)
    else:
        raise AssertionError("string input with commas must raise when split_commas=False")
    assert module.canonical_personas(["adversarial", "code-quality"], split_commas=False) == [
        "adversarial", "code-quality"]


def test_select_returns_required_personas(tmp: Path) -> None:
    result = run("select", "--mode", "changes", "--contract",
                 "--paths", ".cursor/skills/x/SKILL.md", "rules/crew-router.mdc", "evals/a.json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["required"] == [
        "adversarial", "architecture", "code-quality", "product-flow", "prompt-quality"]
    assert json.loads(run("select", "--mode", "pr", "--paths", "x.ts").stdout)["required"] == ["adversarial", "code-quality"]
    assert "prompt-quality" in json.loads(
        run("select", "--mode", "changes", "--paths", "evals/reviewer/helpers.py").stdout
    )["required"]
    # Specs and ideas have no diff to derive lenses from; an empty selection would mean
    # a review could pass with no persona dispatched.
    for mode in ("spec", "idea"):
        spec_required = json.loads(run("select", "--mode", mode).stdout)["required"]
        assert spec_required == ["adversarial", "architecture", "product-flow"], (mode, spec_required)


def test_persist_spec_mode_keeps_code_review(tmp: Path) -> None:
    task = tmp / "task"
    review_dir = task / "review" / "20261102"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    (task / "REVIEW.md").write_text("## Verdict: PASS\n")
    report = tmp / "report.md"
    report.write_text("## Review: Spec\n")
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report), "--mode", "spec",
                 "--personas", "adversarial")
    assert result.returncode == 0, result.stderr
    assert (task / "REVIEW.md").read_text() == "## Verdict: PASS\n"
    # A spec review persists beside the code review rather than over it, and the body it writes keeps
    # its own heading. No `--findings` was supplied, so the footer carries the next step and no derived
    # verdict: `persist` compared nothing, and a `PASS` here would sit under a body that never said so.
    spec_text = (task / "REVIEW.spec.md").read_text()
    assert spec_text.startswith("## Review: Spec\n"), spec_text
    assert spec_text.rstrip().endswith(
        "> Next: approve the revised SPEC.md (Gate 1), then run `crew implement`."), spec_text
    assert "Verdict: PASS" not in spec_text, spec_text


def test_coverage_accepts_a_fully_mapped_diff(tmp: Path) -> None:
    hunks, layers = write_map(tmp, ["h1", "h2", "h3"],
                              [["h1", "h2"], ["h3"]])
    result = run("coverage", "--hunks", str(hunks), "--layers", str(layers))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"hunks": 3, "layers": 2}


def test_coverage_rejects_missing_duplicated_and_unknown_hunks(tmp: Path) -> None:
    """Each failure is a hunk nobody was asked to read, or one claimed twice.

    A layer map that passes validation but skips a hunk is the failure mode this gate exists
    for: the review looks complete and one part of the diff was never reviewed.
    """
    known = ["h1", "h2", "h3"]
    cases = {
        "unassigned": [[["h1", "h2"]], "h3"],
        "duplicated": [[["h1", "h2"], ["h2", "h3"]], "both"],
        "unknown": [[["h1", "h2", "h3", "h9"]], "unknown hunk"],
        "empty layer": [[["h1", "h2", "h3"], []], "non-empty"],
        "no layers": [[], "non-empty"],
        "non-string id": [[["h1", ["h2"], "h3"]], "non-string id"],
    }
    for name, (mapping, needle) in cases.items():
        hunks, layers = write_map(tmp, known, mapping)
        result = run("coverage", "--hunks", str(hunks), "--layers", str(layers))
        assert result.returncode == 2, f"{name}: expected failure, got {result.stdout}"
        assert needle in result.stderr, f"{name}: {result.stderr}"


def test_coverage_rejects_non_object_hunk_entries_and_malformed_notes(tmp: Path) -> None:
    hunks = tmp / "hunks.json"
    layers = tmp / "layers.json"
    hunks.write_text(json.dumps({"files": [], "hunks": [None]}))
    layers.write_text(json.dumps({"layers": []}))
    result = run("coverage", "--hunks", str(hunks), "--layers", str(layers))
    assert result.returncode == 2 and "every hunk must be an object" in result.stderr, result.stderr

    hunks.write_text(json.dumps({"files": [], "hunks": [{"id": "h1"}]}))
    layers.write_text(json.dumps({"layers": [{
        "id": "L1", "explainer": "why", "reviewFocus": "- verify", "hunks": ["h1"], "hunkNotes": []
    }]}))
    result = run("coverage", "--hunks", str(hunks), "--layers", str(layers))
    assert result.returncode == 2 and "hunkNotes must be an object" in result.stderr, result.stderr


def test_persist_strict_runs_coverage_only_when_layers_exist(tmp: Path) -> None:
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    report = tmp / "report.md"
    report.write_text("## Verdict: PASS\n")
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", no_findings(tmp),
            "--strict", "--personas", "adversarial")
    # No hunk index and no layer map: nothing to cover, so the gate stays out of the way.
    assert run(*args).returncode == 0, run(*args).stderr
    (review_dir / "hunks.json").write_text(json.dumps({"files": [], "hunks": [{"id": "h1"}]}))
    (review_dir / "layers.json").write_text(
        json.dumps({"layers": [{"id": "L1", "explainer": "why", "reviewFocus": "- verify", "hunks": ["h1"]}]}))
    assert run(*args).returncode == 0
    # An unmapped hunk must block persistence, not warn.
    (review_dir / "hunks.json").write_text(
        json.dumps({"files": [], "hunks": [{"id": "h1"}, {"id": "h2"}]}))
    blocked = run(*args)
    assert blocked.returncode == 2 and "h2" in blocked.stderr, blocked.stderr
    # A layer map without an index cannot be checked at all.
    (review_dir / "hunks.json").unlink()
    orphan = run(*args)
    assert orphan.returncode == 2 and "hunk index" in orphan.stderr, orphan.stderr
    # A stray map is ignored when the caller opts out, so a caller that cannot supply an index
    # still has a way through the gates.
    plain = run("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", no_findings(tmp),
                "--personas", "adversarial", "--lenient")
    assert plain.returncode == 0, plain.stderr
    # A hunk index with no map means the pre-pass failed: persist, but say coverage was skipped.
    (review_dir / "layers.json").unlink()
    (review_dir / "hunks.json").write_text(json.dumps({"files": [], "hunks": [{"id": "h1"}]}))
    skipped = run(*args)
    assert skipped.returncode == 0 and "not enforced" in skipped.stderr, skipped.stderr
    # The gap must reach the persisted artifact, not only stderr: a reader never sees stderr.
    assert "hunk coverage was not enforced" in (review_dir / "REVIEW.md").read_text()


def test_normalize_strict_requires_real_hunk_ids_on_emitted_findings(tmp: Path) -> None:
    hunks, _ = write_map(tmp, ["h1", "h2"], [["h1", "h2"]])
    source = tmp / "c.json"
    base = {"title": "t", "label": "attention", "file": "a.ts", "disposition": "patch",
            "verified": True, "evidence": "a.ts:3", "validation": "read a.ts:1-9",
            "kind": "correctness", "confidence": 4}
    cases = [
        ({**base, "hunks": ["h2"]}, 0, ""),
        (base, 2, "cites no hunk"),
        ({**base, "hunks": ["h9"]}, 2, "unknown hunk"),
        ({**base, "hunks": "h1"}, 2, "list of hunk ids"),
        ({**base, "label": "nit"}, 0, ""),
        ({**base, "disposition": "defer"}, 0, ""),
    ]
    for finding, code, message in cases:
        source.write_text(json.dumps([finding]))
        result = run("normalize", str(source), "--strict", "--hunks", str(hunks))
        assert result.returncode == code and message in result.stderr, (finding, result.stderr)
    # Without an index there is nothing to check against, so unanchored findings still pass.
    source.write_text(json.dumps([base]))
    assert run("normalize", str(source), "--strict").returncode == 0


def test_normalize_strict_merges_duplicate_hunks_and_validates_each_candidate(tmp: Path) -> None:
    hunks, _ = write_map(tmp, ["h1", "h2"], [["h1", "h2"]])
    source = tmp / "c.json"
    base = {"title": "t", "label": "attention", "file": "a.ts", "disposition": "patch",
            "verified": True, "evidence": "a.ts:3", "persona": ["adversarial"],
            "validation": "read a.ts:1-9", "kind": "correctness", "confidence": 4}
    source.write_text(json.dumps([
        {**base, "hunks": ["h1"]},
        {**base, "persona": ["code-quality"], "hunks": ["h2", "h1"]},
    ]))
    result = run("normalize", str(source), "--strict", "--hunks", str(hunks))
    assert result.returncode == 0, result.stderr
    normalized = json.loads(result.stdout)
    assert normalized["findings"][0]["hunks"] == ["h1", "h2"]
    assert normalized["findings"][0]["persona"] == ["adversarial", "code-quality"]

    # Validation happens before deduplication, so a malformed duplicate cannot disappear.
    source.write_text(json.dumps([{**base, "hunks": ["h1"]}, {**base, "hunks": "h2"}]))
    malformed = run("normalize", str(source), "--strict", "--hunks", str(hunks))
    assert malformed.returncode == 2 and "list of hunk ids" in malformed.stderr, malformed.stderr


def test_persist_strict_appends_coverage_by_layer(tmp: Path) -> None:
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    (review_dir / "hunks.json").write_text(
        json.dumps({"files": [], "hunks": [{"id": "h1"}, {"id": "h2"}]}))
    (review_dir / "layers.json").write_text(json.dumps({"layers": [
        {"id": "L1", "title": "Contract", "explainer": "why", "reviewFocus": "- verify", "hunks": ["h1"]},
        {"id": "L2", "explainer": "why", "reviewFocus": "- verify", "hunks": ["h2"]},
    ]}))
    report = tmp / "report.md"
    report.write_text("## Review: changes\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n"
                      "2. [nit · 5] — Rename\n")
    findings = tmp / "findings.json"
    findings.write_text(json.dumps([
        {"title": "Guard missing", "label": "attention", "disposition": "patch", "hunks": ["h1"],
         "verified": True, "evidence": "a.ts:3", "validation": "read a.ts:1-9",
         "kind": "correctness", "confidence": 4},
        {"title": "Rename", "label": "nit", "disposition": "patch", "kind": "other",
         "confidence": 5},
        {"title": "Old bug", "label": "attention", "disposition": "defer", "kind": "reliability",
         "confidence": 4},
    ]))
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report),
            "--findings", str(findings), "--strict", "--personas", "adversarial")
    result = run(*args)
    assert result.returncode == 0, result.stderr
    written = (review_dir / "REVIEW.md").read_text()
    assert "### Coverage by layer" in written
    assert "- Contract (h1): [attention · 4] Guard missing" in written
    assert "- L2 (h2): no findings" in written
    assert "- outside the map: [nit · 5] Rename" in written
    assert "Old bug" not in written.split("### Coverage by layer", 1)[1]
    # The same gate rejects an emitted finding that cites a hunk outside the index.
    findings.write_text(json.dumps([
        {"title": "Ghost", "label": "attention", "disposition": "patch", "hunks": ["h7"],
         "kind": "correctness", "confidence": 4}]))
    blocked = run(*args)
    assert blocked.returncode == 2 and "unknown hunk" in blocked.stderr, blocked.stderr


def test_coverage_checks_each_layer_shape(tmp: Path) -> None:
    """At most eight layers, a reviewFocus on each, and a hunk note only for the layer's own hunk."""
    known = [f"h{index}" for index in range(1, 10)]
    hunks, _ = write_map(tmp, known, [known])
    layer = {"id": "L1", "explainer": "why", "reviewFocus": "- verify", "hunks": known}
    cases = (
        ([{**layer, "id": f"L{i}", "hunks": [hunk]} for i, hunk in enumerate(known, 1)], "exceeds the maximum of 8"),
        ([{key: value for key, value in layer.items() if key != "reviewFocus"}], "reviewFocus is missing"),
        ([{**layer, "hunks": known[:1]}, {**layer, "id": "L2", "hunks": known[1:], "hunkNotes": {"h1": "note"}}], "not in its hunks"),
        ([{**layer, "hunkNotes": {"h2": "note"}}], None),
    )
    layers = tmp / "shaped.json"
    for mapping, needle in cases:
        layers.write_text(json.dumps({"layers": mapping}))
        result = run("coverage", "--hunks", str(hunks), "--layers", str(layers))
        assert (result.returncode == 0) if needle is None else (result.returncode == 2 and needle in result.stderr), (needle, result.stderr)


SPEC = """# Spec
## Status
IMPLEMENTING
## Summary
Make the parser reject an empty token instead of returning null.
## Acceptance criteria
- [ ] parse("") raises EmptyTokenError
## Tasks
- [ ] Task 1: add EmptyTokenError to src/parser/errors.ts and export it
- [ ] Task 2: throw it from parseToken in src/parser/parse.ts before lookup
```md
## Tasks inside a fence is quoted, not a section
```
## Hints
- The lexer already strips whitespace before parseToken sees the token text
"""


def test_spec_context_keeps_builder_sections_for_product_flow_only(tmp: Path) -> None:
    spec = tmp / "SPEC.md"
    spec.write_text(SPEC)
    flow = run("spec-context", "--persona", "product-flow", str(spec))
    assert flow.returncode == 0 and flow.stdout == SPEC
    other = run("spec-context", "--persona", "reviewer-adversarial", str(spec))
    assert other.returncode == 0, other.stderr
    assert "## Acceptance criteria" in other.stdout and "parse(\"\") raises" in other.stdout
    assert "Task 1" not in other.stdout and "lexer already strips" not in other.stdout
    assert "Tasks and Hints omitted" in other.stdout


# The section every package ends with; the helper appends it so each row tests only its own rule.
QUESTIONS = "\n---\n\n## Questions for this lens\n\n1. Can an empty token reach parseToken?\n2. Who catches EmptyTokenError?\n"


CONTRACT_READS = "## Finding things in the codebase\n\nStop calling tools at your budget.\n\n"


def write_packages(tmp: Path, packages: dict[str, str], stamped: bool = True) -> Path:
    """Packages as the current assembler leaves them: both contract parts, the questions section, and the stamp
    in manifest.json."""
    task = tmp / "task"
    review_dir = task / "review" / "20261118150000"
    review_dir.mkdir(parents=True)
    (task / "SPEC.md").write_text(SPEC)
    for persona, text in packages.items():
        (review_dir / f"{persona}.in.md").write_text(CONTRACT_READS + text + QUESTIONS)
    if stamped:
        (review_dir / "manifest.json").write_text(json.dumps({"personas": {"questions_rule": True}}))
    return review_dir


@pytest.mark.parametrize("questions, problem", [
    ("", "has no `## Questions for this lens` section"),
    ("\n## Questions for this lens\n\n1. Only one?\n\n## Next\n- not a question\n", "asks 1 question(s)"),
    ("\n## Questions for this lens\n\n" + "".join(f"- q{n}?\n" for n in range(6)), "asks 6 question(s)"),
    # A pasted prompt quoting the heading comes first; the section the assembler appends last is the one counted.
    ("\n## Questions for this lens\n\n1. a?\n2. b?\n\n# Prompt tier\n\n## Questions for this lens\n\n1. only?\n",
     "asks 1 question(s)"),
    # Nested bullets belong to their question, so this is 2 questions, not 6.
    ("\n## Questions for this lens\n\n1. a?\n   - x\n   - y\n2. b?\n   - z\n   - w\n", None),
])
def test_check_packages_requires_two_to_five_lens_questions(tmp: Path, questions: str, problem: str | None) -> None:
    review_dir = write_packages(tmp, {})
    (review_dir / "adversarial.in.md").write_text("## Spec\nshort\n" + questions)
    result = run("check-packages", "--review-dir", str(review_dir), "--personas", "adversarial")
    if problem is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1 and problem in result.stderr, result.stderr


def test_check_packages_passes_an_unstamped_directory_with_a_note(tmp: Path) -> None:
    """A review packaged before the questions rule (a resume, say) still dispatches; the skip is reported."""
    review_dir = write_packages(tmp, {}, stamped=False)
    (review_dir / "adversarial.in.md").write_text("## Spec\nshort\n")
    result = run("check-packages", "--review-dir", str(review_dir), "--personas", "adversarial")
    assert result.returncode == 0, result.stderr
    assert "not stamped" in json.loads(result.stdout)["skipped"]["questions"]


@pytest.mark.parametrize("mode", ["spec", "idea", "self"])
def test_check_packages_requires_the_second_contract_part_in_hand_built_packages(tmp: Path, mode: str) -> None:
    """Spec and idea packages are composed by hand; one missing `reviewer-reads.md` loses the tool budget and the
    lookups pointer. Diff-mode packages come from the assembler, which always appends it."""
    review_dir = write_packages(tmp, {"adversarial": "## Spec\nshort\n"})
    path = review_dir / "adversarial.in.md"
    path.write_text(path.read_text().replace(CONTRACT_READS, ""))
    result = run("check-packages", "--review-dir", str(review_dir), "--mode", mode, "--personas", "adversarial")
    refused = "adversarial.in.md has no `## Finding things in the codebase` section" in result.stderr
    assert (result.returncode, refused) == ((1, True) if mode != "self" else (0, False)), result.stderr


def test_check_packages_rejects_copied_tasks_outside_product_flow(tmp: Path) -> None:
    review_dir = write_packages(tmp, {"product-flow": SPEC, "adversarial": SPEC,
                                      "code-quality": "## Spec\n## Summary\nshort\n"})
    result = run("check-packages", "--review-dir", str(review_dir),
                 "--personas", "product-flow", "adversarial", "code-quality")
    assert result.returncode == 1
    assert "adversarial.in.md carries the spec's Tasks/Hints" in result.stderr
    assert "product-flow" not in result.stderr and "code-quality" not in result.stderr
    # A spec review sends every persona the whole spec, so the rule does not apply there.
    assert run("check-packages", "--review-dir", str(review_dir), "--mode", "spec",
               "--personas", "adversarial").returncode == 0


def test_check_packages_rejects_generated_hunks_and_persist_strict_agrees(tmp: Path) -> None:
    lock = "diff --git a/yarn.lock b/yarn.lock\n--- a/yarn.lock\n+++ b/yarn.lock\n@@ -1 +1 @@\n-a\n+b\n"
    review_dir = write_packages(tmp, {"adversarial": lock})
    (review_dir / "hunks.json").write_text(json.dumps({
        "files": [{"path": "yarn.lock", "generated": True, "hunkIds": ["h1"]}],
        "hunks": [{"id": "h1", "file": "yarn.lock"}]}))
    result = run("check-packages", "--review-dir", str(review_dir), "--personas", "adversarial")
    assert result.returncode == 1 and "generated file yarn.lock" in result.stderr
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report = tmp / "report.md"
    report.write_text("## Verdict: PASS\n")
    persist = ("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", no_findings(tmp), "--strict",
               "--personas", "adversarial")
    # A directory packaged before package.diff existed is not held to the package rules.
    assert run(*persist).returncode == 0
    (review_dir / "package.diff").write_text("")
    strict = run(*persist)
    assert strict.returncode == 2 and "generated file yarn.lock" in strict.stderr
    collapsed = lock.split("@@")[0] + "# yarn.lock: likely generated, +1/-1 lines omitted (h1)\n"
    (review_dir / "adversarial.in.md").write_text(collapsed + QUESTIONS)
    assert run("check-packages", "--review-dir", str(review_dir),
               "--personas", "adversarial").returncode == 0


def test_check_packages_copied_line_threshold_is_two(tmp: Path) -> None:
    one = "- [ ] Task 1: add EmptyTokenError to src/parser/errors.ts and export it"
    two = one + "\n- [ ] Task 2: throw it from parseToken in src/parser/parse.ts before lookup"
    review_dir = write_packages(tmp, {"adversarial": one})
    assert run("check-packages", "--review-dir", str(review_dir),
               "--personas", "adversarial").returncode == 0
    (review_dir / "adversarial.in.md").write_text(two)
    assert run("check-packages", "--review-dir", str(review_dir),
               "--personas", "adversarial").returncode == 1


def test_check_packages_reports_skipped_checks_and_rejects_a_wrong_directory(tmp: Path) -> None:
    review_dir = write_packages(tmp, {"adversarial": "clean"})
    ok = run("check-packages", "--review-dir", str(review_dir), "--personas", "adversarial", "code-quality")
    payload = json.loads(ok.stdout)
    assert ok.returncode == 0 and payload["packages"] == 1, "a persona with no package is not counted"
    assert payload["skipped"] == {"hunks": "no hunks.json"}
    elsewhere = tmp / "scratch"
    elsewhere.mkdir()
    (elsewhere / "adversarial.in.md").write_text("clean")
    wrong = run("check-packages", "--review-dir", str(elsewhere), "--personas", "adversarial")
    assert wrong.returncode == 2 and "<task>/review/<timestamp>" in wrong.stderr
    empty = run("check-packages", "--review-dir", str(review_dir), "--personas", "architecture")
    assert empty.returncode == 1 and "no <persona>.in.md found" in empty.stderr


def test_check_packages_matches_git_quoted_header_paths(tmp: Path) -> None:
    quoted = 'diff --git "a/lock files/yarn.lock" "b/lock files/yarn.lock"\n@@ -1 +1 @@\n-a\n+b\n'
    review_dir = write_packages(tmp, {"adversarial": quoted})
    (review_dir / "hunks.json").write_text(json.dumps({
        "files": [{"path": "lock files/yarn.lock", "byName": True, "generated": True, "hunkIds": ["h1"]}],
        "hunks": [{"id": "h1", "file": "lock files/yarn.lock"}]}))
    result = run("check-packages", "--review-dir", str(review_dir), "--personas", "adversarial")
    assert result.returncode == 1 and "generated file lock files/yarn.lock" in result.stderr


def load_module():
    """Import the tool as a module so persona_outcome can be exercised without a subprocess."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("review_findings_for_outcomes", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify(text: str) -> str:
    """`persona_outcome` for a string, through a temporary artifact so the real path is exercised."""
    with tempfile.TemporaryDirectory() as directory:
        artifact = Path(directory) / "p.out.md"
        artifact.write_text(text)
        return load_module().persona_outcome(artifact)


def test_findings_outrank_a_trailing_sentinel(tmp: Path) -> None:
    """A persona emitted anchored findings and then `### Findings: none`.

    Content wins: the sentinel means "nothing to report", never "discard what is above", so the
    artifact stays a completed run and the contradiction is noted rather than resolved by throwing
    evidence away.
    """
    both = ("1. [blocking] **`x-pack/a.ts — line 12`** (h3) — the guard is inverted\n\n"
            "```ts\nif (!ready) return;\n```\n\nIt rejects the ready path.\n\n"
            "Fix: flip the condition.\n\n### Findings: none\n")
    assert classify(both) == "ok"
    # The other direction still holds, so the rule did not become permissive: a bare sentinel is a
    # complete empty review, and a placeholder is still unknown.
    assert classify("### Findings: none\n") == "ok"
    assert classify("status: dispatched\n\nraw response captured\n") == "unknown"


def test_kind_is_required_at_normalize_validated_and_normalized(tmp: Path) -> None:
    """The `kind` field's rules, and the requirement the 2026-11-22 measurement added.

    Absence was legal because every recorded review predates the field; measured, that exemption
    cost the whole axis — 713 of 719 findings carried no `kind`. It is now required, `--lenient`
    is how a legacy artifact is re-read, padding and case are normalized rather than rejected, a
    typo is refused with the vocabulary named, and `kind` stays out of the fingerprint so
    re-classifying a finding cannot create a second one.
    """
    source = tmp / "c.json"
    base = {"title": "t", "label": "nit", "file": "a.ts", "disposition": "patch", "confidence": 5}

    def normalize(payload: list[dict], *flags: str) -> subprocess.CompletedProcess:
        source.write_text(json.dumps(payload))
        return run("normalize", str(source), *flags)

    missing = normalize([base])
    assert missing.returncode == 2, "an absent kind is no longer legal"
    assert "has no kind" in missing.stderr
    for value in sorted(load_module().KINDS):
        assert value in missing.stderr, f"the rejection must name {value}: {missing.stderr}"
    assert normalize([base], "--lenient").returncode == 0, "a legacy artifact stays readable"
    padded = normalize([{**base, "kind": "  Security "}])
    assert padded.returncode == 0
    assert json.loads(padded.stdout)["findings"][0]["kind"] == "security"
    typo = normalize([{**base, "kind": "securty"}])
    assert typo.returncode == 2 and "invalid kind" in typo.stderr
    # Identity is the defect, not its classification: same file, label and title means one finding.
    plain = json.loads(normalize([{**base, "kind": "other"}]).stdout)["findings"][0]["fingerprint"]
    classified = json.loads(normalize([{**base, "kind": "security"}]).stdout)["findings"][0]["fingerprint"]
    assert plain == classified


RAW_REPLY = "### Findings: none\n\nAssessment: approve — the change reads as intended and is covered.\n"


def provenance_review(tmp: Path, personas: tuple[str, ...]) -> tuple[Path, Path]:
    """A review directory with a package per persona and a clean report, ready for save-out."""
    review_dir = tmp / "task" / "review" / "20261126000000"
    review_dir.mkdir(parents=True)
    for persona in personas:
        (review_dir / f"{persona}.in.md").write_text("package")
    report = tmp / "report.md"
    report.write_text("## Review: changes\n")
    return review_dir, report


def save_out(review_dir: Path, persona: str, text: str, *flags: str) -> subprocess.CompletedProcess:
    """In process: `save-out` reads `sys.stdin.buffer`, which the runner must provide."""
    return cli(TOOL, "save-out", "--review-dir", str(review_dir), "--persona", persona, "--harness", "cursor", *flags, stdin=text)


def persist_dir(review_dir: Path, report: Path, personas: tuple[str, ...], *extra: str):
    findings = review_dir.parent.parent / "findings.json"
    findings.write_text("[]") if not findings.exists() else None
    return run("persist", "--review-dir", str(review_dir), "--report", str(report), "--mode", "changes",
               "--findings", str(findings), "--personas", *personas, *extra)


CONTRACT_REPLY = """Assessment: request-changes — the new reader drops the field its only consumer still parses.
Read beyond the package: `src/consumer.py`, `tests/test_reader.py`

1. [attention · 4] **`src/reader.py:12`** — the parser no longer returns `owner`
```
return {"name": name}
```
`src/consumer.py` reads `owner` from every record, so a record read after this change raises KeyError.
Fix: keep `owner` in the returned record.

2. [needs more info · 2] **`src/reader.py:30`** — is the empty-file branch meant to return `None`?
A caller that iterates the result fails on `None`; which callers expect an empty list?
Handoff to adversarial: src/reader.py:40 — a partial write leaves the cache file truncated
"""


def test_persist_accepts_the_read_beyond_and_handoff_lines(tmp: Path) -> None:
    """The reviewer contract puts `Read beyond the package:` after the Assessment line and a `Handoff to <lens>:`
    line after the findings; neither is a finding, and a reply holding both still saves and persists."""
    from crew.review.review_vocabulary import LABEL_LINE, LABELED_FINDING

    review_dir, report = provenance_review(tmp, ("architecture",))
    assert save_out(review_dir, "architecture", CONTRACT_REPLY).returncode == 0
    done = persist_dir(review_dir, report, ("architecture",), "--strict")
    assert done.returncode == 0, done.stderr
    handoff = next(line for line in CONTRACT_REPLY.splitlines() if line.startswith("Handoff to "))
    assert not LABELED_FINDING.search(handoff) and not LABEL_LINE.search(handoff), "a handoff is not a finding"


def test_save_out_stores_the_raw_reply_with_provenance(tmp: Path) -> None:
    """The reply passes through byte for byte; the record carries who, when and a content hash."""
    review_dir, report = provenance_review(tmp, ("adversarial", "code-quality"))
    raw = RAW_REPLY.replace("\n", "\r\n")
    saved = save_out(review_dir, "adversarial", raw, "--agent-id", "agent-1", "--model", "m-1")
    assert saved.returncode == 0, saved.stderr
    assert json.loads(saved.stdout)["saved"] == str(review_dir / "adversarial.out.md"), saved.stdout
    assert (review_dir / "adversarial.out.md").read_bytes() == raw.encode(), "raw bytes, not a rewrite"
    record = json.loads((review_dir / "adversarial.provenance.json").read_text())
    assert record["schema_version"] == 1 and record["harness"] == "cursor"
    assert record["agent_id"] == "agent-1" and record["model"] == "m-1" and record["time"]
    assert len(record["sha256"]) == 64
    assert save_out(review_dir, "code-quality", RAW_REPLY).returncode == 0
    nulls = json.loads((review_dir / "code-quality.provenance.json").read_text())
    assert nulls["agent_id"] is None and nulls["model"] is None, "unknown ids are null, not guessed"
    done = persist_dir(review_dir, report, ("adversarial", "code-quality"))
    assert done.returncode == 0, done.stderr
    assert "provenance: verified" in (review_dir / "REVIEW.md").read_text()


def test_persist_rejects_a_digest_saved_through_save_out(tmp: Path) -> None:
    """save-out keeps the bytes it was given; the digest rejection at persist is unchanged."""
    review_dir, report = provenance_review(tmp, ("adversarial", "code-quality"))
    digest = "[condensed] one finding about a null guard, details omitted\n"
    assert save_out(review_dir, "adversarial", digest).returncode == 0
    assert save_out(review_dir, "code-quality", RAW_REPLY).returncode == 0
    result = persist_dir(review_dir, report, ("adversarial", "code-quality"))
    assert result.returncode == 2 and "condensed digest" in result.stderr, result.stderr
    assert not (review_dir / "REVIEW.md").exists()


def test_persist_rejects_a_reply_edited_after_save_out(tmp: Path) -> None:
    review_dir, report = provenance_review(tmp, ("adversarial",))
    assert save_out(review_dir, "adversarial", RAW_REPLY).returncode == 0
    (review_dir / "adversarial.out.md").write_text(RAW_REPLY + "- [blocking] added later\n")
    result = persist_dir(review_dir, report, ("adversarial",))
    assert result.returncode == 2 and "sha256" in result.stderr and "adversarial" in result.stderr
    assert not (review_dir / "REVIEW.md").exists()


def test_persist_passes_a_review_directory_without_provenance_as_legacy(tmp: Path) -> None:
    """Tamper evidence applies to new reviews only: an absent record is legacy, not a failure."""
    review_dir, report = provenance_review(tmp, ("adversarial",))
    (review_dir / "adversarial.out.md").write_text(RAW_REPLY)
    result = persist_dir(review_dir, report, ("adversarial",))
    assert result.returncode == 0, result.stderr
    text = (review_dir / "REVIEW.md").read_text()
    assert "provenance: absent (legacy)" in text
    assert not text.startswith("Degraded:"), "a legacy review is never reported as degraded"


def test_a_resumed_persona_does_not_trip_the_shared_agent_id_check(tmp: Path) -> None:
    review_dir, report = provenance_review(tmp, ("adversarial", "code-quality"))
    assert save_out(review_dir, "adversarial", RAW_REPLY, "--agent-id", "agent-1").returncode == 0
    # The same persona answers again after a resume, and a null id never counts as shared.
    assert save_out(review_dir, "adversarial", RAW_REPLY, "--agent-id", "agent-1", "--resume").returncode == 0
    assert save_out(review_dir, "code-quality", RAW_REPLY).returncode == 0
    done = persist_dir(review_dir, report, ("adversarial", "code-quality"))
    assert done.returncode == 0, done.stderr
    assert not (review_dir / "REVIEW.md").read_text().startswith("Degraded:")
    assert "degraded" not in json.loads(done.stdout)


def test_distinct_agent_ids_are_not_degraded(tmp: Path) -> None:
    review_dir, report = provenance_review(tmp, ("adversarial", "code-quality"))
    save_out(review_dir, "adversarial", RAW_REPLY, "--agent-id", "agent-1")
    save_out(review_dir, "code-quality", RAW_REPLY, "--agent-id", "agent-2")
    done = persist_dir(review_dir, report, ("adversarial", "code-quality"))
    assert done.returncode == 0, done.stderr
    assert "Verdict: PASS" in (review_dir / "REVIEW.md").read_text()


RESUMED = "### Findings: none\n\nAssessment: approve — re-emitted in full.\n"


def capture_hook(tmp: Path, prompt: str, agent: str, reply: str, handback: bool = True) -> subprocess.CompletedProcess:
    """Run Claude Code's SubagentStop through crew-hook.py on a fixture transcript: the dispatch prompt, then one assistant turn that hands back
    `reply` after the text `Handed back.` (the payload's `last_assistant_message`), or, without `handback`, says
    `reply` as its final text, which `last_assistant_message` then carries, as Claude Code documents."""
    home = tmp / "home"
    if not (home / ".agent" / "bin" / "crew-review-findings.py").exists():
        (home / ".agent" / "bin").mkdir(parents=True, exist_ok=True)
        (home / ".agent" / "bin" / "crew-review-findings.py").symlink_to(launcher("crew-review-findings.py"))
    content = [{"type": "text", "text": "Reviewing." if handback else reply}]
    if handback:
        content.append({"type": "tool_use", "name": "SubagentHandback", "input": {"message": reply}})
    usage = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    lines = [{"type": "user", "message": {"role": "user", "content": prompt}},
             {"type": "assistant", "message": {"role": "assistant", "model": "m-1", "content": content, "usage": usage}}]
    path = tmp / f"{agent}-{len(list(tmp.glob('*.jsonl')))}.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    payload = {"hook_event_name": "SubagentStop", "agent_id": agent, "agent_type": "general-purpose",
               "agent_transcript_path": str(path), "last_assistant_message": "Handed back." if handback else reply}
    return hook(home, payload)


def marker(review_dir: Path, persona: str) -> str:
    done = run("expect", "--review-dir", str(review_dir), "--persona", persona)
    assert done.returncode == 0 and (review_dir / f"{persona}.expect").is_file(), done.stderr
    return done.stdout.strip()


@pytest.mark.parametrize("persona,handback", [("adversarial", True), ("adversarial", False), ("probe", True)])
def test_capture_hook_saves_the_reply_its_marker_names(tmp: Path, persona: str, handback: bool) -> None:
    """The handback message (else the last assistant message) is saved with the hook's harness, agent id and model;
    the `.expect` file stays and the record keeps its nonce as consumed."""
    review_dir, _ = provenance_review(tmp, (persona,))
    line = marker(review_dir, persona)
    done = capture_hook(tmp, f"{line}\n\nReview this package.", "a1", RAW_REPLY, handback)
    assert done.returncode == 0 and "capture-reply: saved" in done.stdout, (done.stdout, done.stderr)
    assert (review_dir / f"{persona}.out.md").read_text() == RAW_REPLY
    record = json.loads((review_dir / f"{persona}.provenance.json").read_text())
    assert (record["harness"], record["agent_id"], record["model"], record["resumed"]) == ("claude-code", "a1", "m-1", False)
    assert record["nonce"] == line.split()[-1] and (review_dir / f"{persona}.expect").exists()
    assert not (review_dir / f"{persona}.unanswered").exists()


@pytest.mark.parametrize("case,says", [("quoted marker", "adversarial: no adversarial.expect for this marker; nothing saved"),
                                       ("wrong nonce", "the marker's nonce does not match adversarial.expect; nothing saved"),
                                       ("a name collision", "answers another dispatch (a name collision); kept")])
def test_capture_hook_saves_nothing_it_cannot_trust(tmp: Path, case: str, says: str) -> None:
    """A marker with no `.expect`, a nonce that does not match, or a second dispatch under a name whose `.out.md`
    answers an earlier marker: nothing is written, each for its own stated reason."""
    review_dir, _ = provenance_review(tmp, ("adversarial",))
    line = f"crew-review-out: {review_dir} adversarial {'0' * 32}"
    if case != "quoted marker":
        real = marker(review_dir, "adversarial")
        line = real if case == "a name collision" else line
    if case == "a name collision":
        assert "saved" in capture_hook(tmp, marker(review_dir, "adversarial"), "a2", RAW_REPLY).stdout
        (review_dir / "adversarial.expect").write_text(line.split()[-1] + "\n")
    done = capture_hook(tmp, f"Quoting a dispatch:\n{line}\n", "a1", RESUMED)
    assert done.returncode == 0 and says in done.stdout, done.stdout
    out = review_dir / "adversarial.out.md"
    assert (out.read_text() == RAW_REPLY) if case == "a name collision" else not out.exists()
    assert (review_dir / "adversarial.expect").exists() is (case != "quoted marker")


@pytest.mark.parametrize("accepted", [True, False])
def test_capture_hook_records_usage_through_an_accepted_marker_only(tmp: Path, accepted: bool) -> None:
    """With no `crew-task:` line, the task above the review directory gets the persona's `agent_end` only when the marker
    was accepted; a quoted marker the nonce check refused records nothing there."""
    task = tmp / "home" / ".agent" / "tasks" / "T"
    review_dir = task / "review" / "20261127000000"
    review_dir.mkdir(parents=True)
    (task / "SPEC.md").write_text("# T\n\n## Status\nIMPLEMENTING\n")
    (review_dir / "adversarial.in.md").write_text("package")
    line = marker(review_dir, "adversarial") if accepted else f"crew-review-out: {review_dir} adversarial {'0' * 32}"
    done = capture_hook(tmp, f"{line}\nReview this package.", "a1", RAW_REPLY)
    progress = (task / "PROGRESS.md").read_text() if (task / "PROGRESS.md").exists() else ""
    assert done.returncode == 0 and ("agent_end agent=general-purpose persona=adversarial agent_id=a1 tokens=150" in progress) is accepted, (
        done.stdout, progress)


def test_capture_hook_resumes_its_own_reply_and_persist_accepts_the_folder(tmp: Path) -> None:
    """A second reply to the same marker is the reply, the first kept as `.prev.md` and the pending mark cleared;
    persist verifies the folder."""
    review_dir, report = provenance_review(tmp, ("adversarial", "code-quality"))
    first = marker(review_dir, "adversarial")
    blocked = json.loads(capture_hook(tmp, first, "a1", "- see above\n").stdout)
    assert blocked["decision"] == "block" and blocked["reason"].startswith("deliver now:"), blocked
    assert (review_dir / "adversarial.unanswered").exists()
    assert "resumed" in capture_hook(tmp, first, "a1", RESUMED).stdout
    assert (review_dir / "adversarial.out.md").read_text() == RESUMED
    assert (review_dir / "adversarial.prev.md").read_text() == "- see above\n"
    assert not (review_dir / "adversarial.unanswered").exists()
    assert json.loads((review_dir / "adversarial.provenance.json").read_text())["resumed"] is True
    assert "saved" in capture_hook(tmp, marker(review_dir, "code-quality"), "a2", RAW_REPLY).stdout
    done = persist_dir(review_dir, report, ("adversarial", "code-quality"))
    assert done.returncode == 0, done.stderr
    assert "provenance: verified" in (review_dir / "REVIEW.md").read_text()


def degraded_findings(tmp: Path, label: str | None) -> None:
    rows = [] if label is None else [{
        "title": "Missing null guard", "label": label, "file": "a.ts", "line": 3, "kind": "correctness",
        "disposition": "patch", "verified": True, "confidence": 4, "evidence": "a.ts:3@abc1234",
        "validation": "read the call site and confirmed the guard is absent",
        "excerpt": "const value = row.data;\nvalue.length;"}]
    (tmp / "task" / "findings.json").write_text(json.dumps(rows))


def test_a_shared_agent_id_is_a_degraded_review_capped_at_warn(tmp: Path) -> None:
    """One agent playing two lenses is persisted, not refused: banner, report line, PASS becomes WARN."""
    review_dir, report = provenance_review(tmp, ("adversarial", "code-quality"))
    save_out(review_dir, "adversarial", RAW_REPLY, "--agent-id", "agent-1")
    save_out(review_dir, "code-quality", RAW_REPLY, "--agent-id", "agent-1")
    degraded_findings(tmp, None)
    report.write_text("## Review: changes\nVerdict: PASS\n")
    stale = persist_dir(review_dir, report, ("adversarial", "code-quality"))
    assert stale.returncode == 2 and "capped at WARN" in stale.stderr, stale.stderr
    report.write_text("## Review: changes\nVerdict: WARN\n")
    done = persist_dir(review_dir, report, ("adversarial", "code-quality"))
    assert done.returncode == 0, done.stderr
    text = (review_dir / "REVIEW.md").read_text()
    assert text.startswith("Degraded: 1 agent, 2 lenses"), text[:80]
    assert "\nVerdict: WARN\n" in text and "Verdict: PASS" not in text
    assert json.loads(done.stdout)["degraded"] == "Degraded: 1 agent, 2 lenses"


def test_a_declared_degraded_review_keeps_block_as_block(tmp: Path) -> None:
    """A fork that plays every lens has no ids to compare, so the orchestrator declares it; BLOCK stays BLOCK."""
    review_dir, report = provenance_review(tmp, ("adversarial", "code-quality"))
    for persona in ("adversarial", "code-quality"):
        save_out(review_dir, persona, "- [blocking] Missing null guard\nAnchor: a.ts:3\n", "--degraded")
    degraded_findings(tmp, "blocking")
    report.write_text("## Review: changes\nVerdict: BLOCK\n\n1. [blocking · 4] — Missing null guard\n"
                      "   Anchor: a.ts:3\n")
    done = persist_dir(review_dir, report, ("adversarial", "code-quality"), "--files", "a.ts")
    assert done.returncode == 0, done.stderr
    text = (review_dir / "REVIEW.md").read_text()
    assert text.startswith("Degraded: 1 agent, 2 lenses") and "\nVerdict: BLOCK\n" in text


def candidate(title: str, line: int, label: str = "attention", persona: str = "adversarial", **extra) -> dict:
    return {"title": title, "label": label, "kind": "correctness", "file": "a.ts", "line": line,
            "persona": persona, "disposition": "patch", "verified": True, "confidence": 4,
            "evidence": f"a.ts:{line}", "validation": "read the call site", **extra}


def consolidate_raw(directory: Path, rows: list) -> tuple[Path, subprocess.CompletedProcess]:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw-candidates.json").write_text(json.dumps(rows))
    (directory / "hunks.json").write_text(json.dumps({"files": [], "hunks": [
        {"id": "h1", "file": "a.ts", "lines": [{"t": "+", "s": "x", "n": n} for n in range(1, 8)]},
        {"id": "h2", "file": "a.ts", "lines": [{"t": "+", "s": "x", "n": n} for n in range(20, 30)]}]}))
    return directory, run("consolidate", "--review-dir", str(directory))


def test_consolidate_groups_overlap_only_and_never_rewrites_a_label(tmp: Path) -> None:
    """Same file and overlapping lines group; a second defect ten lines away stays its own finding."""
    rows = [candidate("Missing null guard", 3, "blocking", "adversarial", line_end=5),
            candidate("Guard absent on empty row", 4, "attention", "code-quality"),
            candidate("Off by one in the loop", 25, "attention", "architecture")]
    review_dir, done = consolidate_raw(tmp / "review", rows)
    assert done.returncode == 0, done.stderr
    draft = json.loads((review_dir / "candidates.json").read_text())
    assert draft["schema_version"] == 1 and len(draft["groups"]) == 1, draft["groups"]
    first, second, third = draft["findings"]
    assert (first["label"], second["label"], third["label"]) == ("blocking", "attention", "attention")
    assert first["group_severity"] == "blocking" and second["disposition"] == "merged"
    assert second["merged_into"] == first["group"] == "g1" and "group" not in third, "merged_into is the group id, not a title"
    assert third["disposition"] == "patch" and (first["hunks"], third["hunks"]) == (["h1"], ["h2"])
    apart, done = consolidate_raw(tmp / "apart", [candidate("One", 3), candidate("Two", 13)])
    assert done.returncode == 0 and json.loads((apart / "candidates.json").read_text())["groups"] == [], \
        "two distinct defects 10 lines apart stay two findings"
    normalized = run("normalize", str(review_dir / "candidates.json"), "--hunks", str(review_dir / "hunks.json"),
                     "--output", str(review_dir / "consolidation.json"))
    assert normalized.returncode == 0, normalized.stderr


def test_consolidation_renders_a_report_persist_accepts(tmp: Path) -> None:
    """`report.md` carries each finding's body (its comment's first paragraph) and a blocking finding's excerpt, so
    it is the reply verbatim; persist accepts it and lists the stdin-saved (`manual`) reply under `### Reviewers`."""
    body = "Could `row` be null here? The caller passes `None` on an empty page.\n\nSecond paragraph stays out."
    rows = [candidate("Missing null guard", 3, "blocking", "adversarial", comment=body,
                      excerpt="const value = row.data;"),
            candidate("Guard absent on empty row", 3, "attention", "adversarial")]
    review_dir, done = consolidate_raw(tmp / "review", rows)
    assert done.returncode == 0, done.stderr
    consolidation = review_dir / "consolidation.json"
    assert run("normalize", str(review_dir / "candidates.json"), "--output", str(consolidation)).returncode == 0
    rendered = run("consolidate", "--review-dir", str(review_dir), "--render", "--mode", "changes")
    assert rendered.returncode == 0, rendered.stderr
    text = (review_dir / "report.md").read_text()
    assert "merged 1 duplicates" in text and "originals:" in text and "Guard absent on empty row" in text, text
    assert text.count("\n1. [blocking") == 1 and "\n2. " not in text, text
    assert "   > Could `row` be null here? The caller passes `None` on an empty page.\n" in text, text
    assert "Second paragraph" not in text and "   ```\n   const value = row.data;\n   ```\n" in text, text
    out_dir = tmp / "task" / "review" / "20261126000000"
    out_dir.mkdir(parents=True)
    (out_dir / "adversarial.in.md").write_text("package")
    assert save_out(out_dir, "adversarial", "- [blocking] Missing null guard\nAnchor: a.ts:3\n").returncode == 0
    persisted = run("persist", "--review-dir", str(out_dir), "--report", str(review_dir / "report.md"),
                    "--mode", "changes", "--findings", str(consolidation), "--personas", "adversarial",
                    "--files", "a.ts")
    assert persisted.returncode == 0, persisted.stderr
    review = (out_dir / "REVIEW.md").read_text()
    assert "Verdict: BLOCK" in review and json.loads((out_dir / "adversarial.provenance.json").read_text())["source"] == "manual"
    assert "### Reviewers\n\n- adversarial: reply saved by hand (`save-out` from stdin)" in review, review


@pytest.mark.parametrize("comment", ["`a.py:10` calls the old name.", "2 [attention] looks like a second finding.",
                                     "Verdict: PASS, says this body."],
                         ids=["an anchor in the body", "a numbered label", "a verdict line"])
def test_a_rendered_body_is_never_read_as_structure(tmp: Path, comment: str) -> None:
    """The quoted body line cannot become a finding's anchor, an extra finding or the verdict: a finding with no
    `file:line` whose comment names one, or a body opening like a label or a verdict, still persists unchanged."""
    anchorless = candidate("Spec and code disagree", 3, "concern", "adversarial", comment=comment,
                           evidence="SPEC.md Tasks section")
    del anchorless["file"], anchorless["line"]
    review_dir, done = consolidate_raw(tmp / "review", [anchorless])
    assert done.returncode == 0, done.stderr
    consolidation = review_dir / "consolidation.json"
    normalized = run("normalize", str(review_dir / "candidates.json"), "--output", str(consolidation))
    assert normalized.returncode == 0, normalized.stderr
    assert run("consolidate", "--review-dir", str(review_dir), "--render", "--mode", "changes").returncode == 0
    assert f"   > {comment}\n" in (review_dir / "report.md").read_text()
    out_dir = tmp / "task" / "review" / "20261126000000"
    out_dir.mkdir(parents=True)
    (out_dir / "adversarial.in.md").write_text("package")
    assert save_out(out_dir, "adversarial", RAW_REPLY).returncode == 0
    persisted = run("persist", "--review-dir", str(out_dir), "--report", str(review_dir / "report.md"),
                    "--mode", "changes", "--findings", str(consolidation), "--personas", "adversarial")
    assert persisted.returncode == 0, persisted.stderr
    assert "Verdict: PASS" in (out_dir / "REVIEW.md").read_text() or "Verdict: WARN" in (out_dir / "REVIEW.md").read_text()


def test_save_out_from_transcript_extracts_the_reply_and_checks_its_marker(tmp: Path) -> None:
    """`save-out --from-transcript` saves the transcript's reply as the hook would, `source: transcript`, and persist
    lists nothing under `### Reviewers`; a transcript whose marker names another persona is refused."""
    review_dir, report = provenance_review(tmp, ("adversarial",))
    line = marker(review_dir, "adversarial")
    path = tmp / "t.jsonl"
    path.write_text("".join(json.dumps(item) + "\n" for item in [
        {"role": "user", "message": {"content": [{"type": "text", "text": f"<user_query>\n{line}\n</user_query>"}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": RAW_REPLY}]}}]))
    wrong = run("save-out", "--review-dir", str(review_dir), "--persona", "code-quality", "--harness", "cursor",
                "--from-transcript", str(path))
    assert wrong.returncode == 2 and "not " in wrong.stderr, wrong
    done = run("save-out", "--review-dir", str(review_dir), "--persona", "adversarial", "--harness", "cursor",
               "--from-transcript", str(path))
    assert done.returncode == 0 and "save-out: saved" in done.stdout, (done.stdout, done.stderr)
    assert (review_dir / "adversarial.out.md").read_text() == RAW_REPLY
    record = json.loads((review_dir / "adversarial.provenance.json").read_text())
    assert (record["source"], record["nonce"], record["harness"]) == ("transcript", line.split()[-1], "cursor")
    persisted = persist_dir(review_dir, report, ("adversarial",))
    assert persisted.returncode == 0 and "### Reviewers" not in (review_dir / "REVIEW.md").read_text(), persisted.stderr


def test_two_groups_with_one_title_keep_their_own_originals(tmp: Path) -> None:
    rows = [candidate("Same title", 3, "blocking"), candidate("Duplicate of the first group", 3, "attention"),
            candidate("Same title", 25, "attention"), candidate("Duplicate of the second group", 25, "nit")]
    review_dir, done = consolidate_raw(tmp / "review", rows)
    assert done.returncode == 0, done.stderr
    assert len(json.loads((review_dir / "candidates.json").read_text())["groups"]) == 2
    assert run("normalize", str(review_dir / "candidates.json"), "--output", str(review_dir / "consolidation.json")).returncode == 0
    assert run("consolidate", "--review-dir", str(review_dir), "--render", "--mode", "changes").returncode == 0
    text = (review_dir / "report.md").read_text()
    first, second = text.split("\n2. ")
    assert "Duplicate of the first group" in first and "Duplicate of the second group" not in first, text
    assert "Duplicate of the second group" in second and "Duplicate of the first group" not in second, text


def test_different_kinds_at_one_line_stay_separate_findings(tmp: Path) -> None:
    rows = [candidate("Wrong result", 3, "attention"), candidate("Unescaped input", 3, "attention", kind="security"),
            candidate("Also wrong", 3, "nit")]
    review_dir, done = consolidate_raw(tmp / "review", rows)
    assert done.returncode == 0, done.stderr
    draft = json.loads((review_dir / "candidates.json").read_text())
    kinds = {f["title"]: f.get("disposition") for f in draft["findings"]}
    assert kinds["Unescaped input"] == "patch" and "group" not in draft["findings"][1], draft
    assert kinds["Also wrong"] == "merged" and len(draft["groups"]) == 1, draft["groups"]


def test_a_deferred_finding_never_absorbs_an_emitted_one(tmp: Path) -> None:
    """Only patch and decide findings group; a defer or dropped member keeps its own disposition."""
    rows = [candidate("Pre-existing crash", 3, "blocking", disposition="defer"),
            candidate("New guard missing", 3, "attention"),
            candidate("Dropped duplicate", 3, "attention", disposition="dropped")]
    review_dir, done = consolidate_raw(tmp / "review", rows)
    assert done.returncode == 0, done.stderr
    draft = json.loads((review_dir / "candidates.json").read_text())
    kinds = {f["title"]: f.get("disposition") for f in draft["findings"]}
    assert kinds == {"Pre-existing crash": "defer", "New guard missing": "patch", "Dropped duplicate": "dropped"}, kinds
    assert draft["groups"] == [] and all("group" not in f for f in draft["findings"]), draft
    rows = [candidate("Decide this", 3, "blocking", disposition="decide", line_end=5), candidate("Patch this", 4, "attention"),
            candidate("Deferred", 4, "blocking", disposition="defer")]
    review_dir, done = consolidate_raw(tmp / "mixed", rows)
    draft = json.loads((review_dir / "candidates.json").read_text())
    kinds = {f["title"]: f.get("disposition") for f in draft["findings"]}
    assert kinds == {"Decide this": "decide", "Patch this": "merged", "Deferred": "defer"}, kinds
    assert draft["groups"][0]["members"] == ["Decide this", "Patch this"], draft["groups"]


def test_a_hand_set_anchor_marker_is_not_trusted(tmp: Path) -> None:
    source = tmp / "c.json"
    doc = {**candidate("Stale doc", 1, "attention"), "file": "README.md", "evidence": "README.md:1", "anchor": "non-hunk"}
    source.write_text(json.dumps([doc]))
    done = run("normalize", str(source), "--files", "a.ts")
    assert done.returncode == 2, "an incoming anchor marker must not skip the evidence-in-set rule: " + done.stdout


def anchored_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "PATH": os.environ["PATH"]}
    (repo / "a.ts").write_text("x\n")
    (repo / "README.md").write_text("docs\n")
    for command in (["init", "-q"], ["add", "a.ts", "README.md"], ["commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(repo), *command], check=True, env=env, capture_output=True)
    (repo / "scratch.md").write_text("untracked\n")
    return repo


def test_an_anchor_outside_the_diff_must_be_tracked_and_blocking_needs_a_read_line(tmp: Path) -> None:
    repo = anchored_repo(tmp)
    source = tmp / "c.json"

    def normalize_with(finding: dict) -> subprocess.CompletedProcess:
        source.write_text(json.dumps([finding]))
        return run("normalize", str(source), "--files", "a.ts", "--repo", str(repo), "--head", "HEAD")

    doc = {**candidate("Stale doc", 1, "attention"), "file": "README.md", "evidence": "README.md:1"}
    ok = normalize_with(doc)
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["findings"][0]["anchor"] == "non-hunk", "marked, and no hunk id demanded"
    untracked = normalize_with({**doc, "file": "scratch.md", "evidence": "scratch.md:1"})
    assert untracked.returncode == 2 and "not a tracked file" in untracked.stderr, untracked.stderr
    unread = normalize_with({**doc, "label": "blocking"})
    assert unread.returncode == 2 and "line_read" in unread.stderr, unread.stderr
    assert normalize_with({**doc, "label": "blocking", "line_read": True}).returncode == 0
    source.write_text(json.dumps([doc]))
    assert run("normalize", str(source), "--files", "a.ts").returncode == 2, "without --repo the old rule stands"
    # A PR head the checkout does not hold: the refusal names the PR-mode call.
    absent = run("normalize", str(source), "--files", "a.ts", "--repo", str(repo), "--head", "f" * 40)
    assert absent.returncode == 2 and "leave out --repo and --head" in absent.stderr, absent.stderr


def probe_persist(tmp: Path, label: str = "needs more info", tail: str = "", *extra: str) -> subprocess.CompletedProcess:
    """Persist one emitted unsettled finding (score 2) under `label`; `tail` follows the numbered list."""
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report, findings = tmp / "report.md", tmp / "findings.json"
    findings.write_text(json.dumps([{"title": "Unsettled guard", "label": label,
                                     "disposition": "patch", "kind": "correctness", "confidence": 2}]))
    report.write_text(f"## Verdict: PASS\n\n1. [{label} · 2] — Unsettled guard\n{tail}")
    return run("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", str(findings),
               "--personas", "adversarial", *(extra or ("--mode", "changes")))


def test_persist_requires_a_probe_record_for_an_unsettled_finding(tmp: Path) -> None:
    """The probe reply counts only when `save-out --persona probe` saved it with its provenance record."""
    refused = probe_persist(tmp)
    assert refused.returncode == 2 and "--persona probe" in refused.stderr, refused.stderr
    review_dir = tmp / "task" / "review" / "ts"
    (review_dir / "probe.out.md").write_text("ran: npm test -- guard\nobserved: inconclusive\n")
    unrecorded = probe_persist(tmp)
    assert unrecorded.returncode == 2 and "no matching provenance record" in unrecorded.stderr, unrecorded.stderr
    saved = save_out(review_dir, "probe", "ran: npm test -- guard\nobserved: inconclusive\n")
    assert saved.returncode == 0 and (review_dir / "probe.provenance.json").is_file(), saved.stderr
    assert probe_persist(tmp).returncode == 0, probe_persist(tmp).stderr


def test_persist_needs_findings_outside_pr_mode_and_probes_any_low_score(tmp: Path) -> None:
    """Without `--findings` the probe gate cannot run, so self and changes refuse; PR mode never probes."""
    report = tmp / "bare.md"
    report.write_text("## Review: changes\n")
    bare = run("persist", "--review-dir", str(tmp / "task" / "review" / "ts"), "--report", str(report), "--mode", "changes")
    assert bare.returncode == 2 and "requires --findings" in bare.stderr, bare.stderr
    pr = probe_persist(tmp / "pr", "needs more info", "", "--mode", "pr", "--head", "0123456789abcdef0123456789abcdef01234567")
    assert pr.returncode == 0, pr.stderr
    nit = probe_persist(tmp / "nit", "nit")
    assert nit.returncode == 2 and "reviewer-probe" in nit.stderr, nit.stderr


def test_a_skipped_probe_names_why_it_cannot_run_and_settles_nothing(tmp: Path) -> None:
    """`probe: skipped` takes a reason from the fixed vocabulary, and the finding stays `[needs more info]`."""
    vague = probe_persist(tmp, "needs more info", "\nprobe: skipped not worth it\n")
    assert vague.returncode == 2 and "no-runtime" in vague.stderr, vague.stderr
    assert probe_persist(tmp, "needs more info", "\nprobe: skipped no-runtime: no test runner in this checkout\n").returncode == 0
    relabelled = probe_persist(tmp / "nit", "nit", "\nprobe: skipped no-network: the API is offline\n")
    assert relabelled.returncode == 2 and "[needs more info]" in relabelled.stderr, relabelled.stderr


def candidate_file(tmp: Path, **overrides: object) -> Path:
    """One verified, anchored attention finding at confidence 4; an override replaces a field, None drops it."""
    finding = {"title": "Guard missing", "label": "attention", "file": "a.ts", "line": 3, "disposition": "patch",
               "verified": True, "evidence": "a.ts:3", "kind": "correctness", "confidence": 4,
               "validation": "read a.ts:1-9; the guard is absent"}
    for key, value in overrides.items():
        if value is None:
            finding.pop(key, None)
        else:
            finding[key] = value
    source = tmp / "candidates.json"
    source.write_text(json.dumps([finding]))
    return source


def gated_persist(tmp: Path, mode: str, *extra: str, **overrides: object) -> tuple[subprocess.CompletedProcess, Path, tuple]:
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "adversarial.in.md").write_text("in")
    (review_dir / "adversarial.out.md").write_text("### Findings: none\n")
    report = tmp / "report.md"
    report.write_text("## Review: Spec\n" if mode == "spec" else "## Verdict: WARN\n\n1. [attention · 4] **`a.ts:3`** — Guard missing\n")
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report), "--findings", str(candidate_file(tmp, **overrides)),
            "--mode", mode, "--personas", "adversarial", *extra)
    return run(*args), review_dir, args


def test_persist_applies_the_gates_without_a_flag_and_lenient_is_the_escape(tmp: Path) -> None:
    """The documented invocation is the enforced one, in every mode, and a gated run writes nothing."""
    for mode, extra, gate in (("changes", ("--files", "a.ts"), "records no validation sentence"),
                              ("spec", (), "records no validation sentence")):
        result, review_dir, args = gated_persist(tmp / mode, mode, *extra, validation=None)
        assert result.returncode == 2 and gate in result.stderr, (mode, result.stderr)
        assert not (review_dir / "REVIEW.md").exists() and not (tmp / mode / "task" / "REVIEW.spec.md").exists()
    _, review_dir, args = gated_persist(tmp / "lenient", "changes", "--files", "a.ts", validation=None)
    assert run(*args, "--lenient").returncode == 0 and (review_dir / "REVIEW.md").is_file()
    # `--strict` is the default's old spelling and cannot re-enable what `--lenient` turned off.
    source = candidate_file(tmp, validation=None)
    assert run("normalize", str(source), "--lenient", "--strict").returncode == 0


def test_kind_is_required_at_persist_and_names_every_value(tmp: Path) -> None:
    result, review_dir, args = gated_persist(tmp, "changes", kind=None)
    assert result.returncode == 2 and "has no kind" in result.stderr, result.stderr
    for value in ("security", "correctness", "reliability", "documentation", "testing", "other"):
        assert value in result.stderr, f"the rejection must name {value}: {result.stderr}"
    assert not (review_dir / "REVIEW.md").exists()
    assert run(*args, "--lenient").returncode == 0, "a finding written before kind is still readable"


def outcome_dir(tmp: Path) -> Path:
    directory = tmp / "task" / "review" / "20261122120000"
    directory.mkdir(parents=True)
    (directory / "findings.json").write_text(json.dumps({"findings": [
        {"title": "Guard missing", "label": "attention", "disposition": "patch", "fingerprint": "aaa111",
         "persona": ["adversarial"], "kind": "correctness"},
        {"title": "Rename helper", "label": "nit", "disposition": "patch", "fingerprint": "bbb222",
         "persona": ["code-quality"], "kind": "other"}]}))
    return directory


def log_outcome(directory: Path, fingerprint: str, outcome: str, review_dir: str = "", *extra: str) -> subprocess.CompletedProcess:
    return run("outcome", "--review-dir", review_dir or str(directory), "--fingerprint", fingerprint, "--persona", "adversarial",
               "--label", "attention", "--outcome", outcome, "--reason", "applied in the pass", *extra)


def outcomes(directory: Path, *acted: str) -> tuple[int, dict]:
    result = run("outcomes", "--review-dir", str(directory), *(("--acted", *acted) if acted else ()))
    return result.returncode, json.loads(result.stdout or "{}")


def test_one_outcome_per_decision_the_latest_wins_and_a_gap_fails(tmp: Path) -> None:
    """Two decisions write two lines; an untouched finding stays unrecorded; a later decision supersedes."""
    directory = outcome_dir(tmp)
    code, payload = outcomes(directory)
    assert code == 0 and payload["recorded"] == 0, "an absent journal is an answer, not a failure"
    log_outcome(directory, "aaa111", "fixed")
    code, payload = outcomes(directory, "aaa111", "bbb222")
    assert code == 1 and payload["missing"] == ["bbb222"], payload
    log_outcome(directory, "bbb222", "deferred")
    log_outcome(directory, "bbb222", "rejected")
    journal = tmp / "task" / "review" / "outcomes.jsonl"
    assert len(journal.read_text().splitlines()) == 3
    code, payload = outcomes(directory, "aaa111", "bbb222")
    assert code == 0 and payload["recorded"] == 2 and payload["missing"] == [] and payload["outcomes"] == {"fixed": 1, "rejected": 1}, payload


def test_a_relative_review_dir_attributes_to_its_own_review(tmp: Path) -> None:
    directory = outcome_dir(tmp)
    saved = os.getcwd()
    try:
        os.chdir(directory)
        assert log_outcome(directory, "aaa111", "fixed", ".").returncode == 0
    finally:
        os.chdir(saved)
    payload = outcomes(directory)[1]
    assert payload["recorded"] == 1 and payload["fingerprints"] == ["aaa111"], payload


def probe_normalize(tmp: Path, **overrides: object) -> subprocess.CompletedProcess:
    return run("normalize", str(candidate_file(tmp, **overrides)))


def test_a_probe_moves_a_score_only_with_its_evidence(tmp: Path) -> None:
    """A confirming probe may raise a score; only a refuting probe may lower one, and only off a request."""
    raised = probe_normalize(tmp, confidence_from=2, probe="confirmed", validation="ran `node --test g.js`; it fails without the guard")
    assert raised.returncode == 0 and json.loads(raised.stdout)["findings"][0]["probe"] == "confirmed", raised.stderr
    asking = {"label": "needs more info", "disposition": "decide", "verified": None, "evidence": None}
    lowered = probe_normalize(tmp, **asking, confidence=1, confidence_from=4, probe="refuted", validation="ran `pytest`; the guard fires first")
    assert lowered.returncode == 0 and json.loads(lowered.stdout)["findings"][0]["confidence"] == 1, lowered.stderr
    unmeasured = probe_normalize(tmp, **{**asking, "verified": True, "evidence": "a.ts:3"}, confidence=2, confidence_from=4,
                                 validation="read a.ts:1-9 again; the guard is there")
    assert unmeasured.returncode == 2 and "only ever moves up" in unmeasured.stderr and "refuted" in unmeasured.stderr, unmeasured.stderr
    request = probe_normalize(tmp, confidence=2, confidence_from=3, probe="refuted", validation="ran `pytest`; the loop fires once")
    assert request.returncode == 2 and "refuted request is not a request" in request.stderr and "needs more info" in request.stderr, request.stderr
    for bad in ("refutes", "", 7):
        result = probe_normalize(tmp, probe=bad)
        assert result.returncode == 2 and "invalid probe" in result.stderr and "confirmed, inconclusive, refuted" in result.stderr, (bad, result.stderr)
    bare = {"label": "nit", "probe": "refuted", "verified": None, "evidence": None}
    assert "no validation sentence" in probe_normalize(tmp, **bare, validation=None).stderr
    assert probe_normalize(tmp, **bare, validation="ran the probe; the guard fires once").returncode == 0


def test_a_score_move_recorded_as_an_outcome_needs_its_evidence(tmp: Path) -> None:
    directory = tmp / "review" / "ts"
    directory.mkdir(parents=True)

    def move(*extra: str) -> subprocess.CompletedProcess:
        return log_outcome(directory, "c3", "fixed", "", *extra)

    sentence = ("--validation", "ran the probe; the guard fires first")
    assert "--validation" in move("--confidence", "4", "--confidence-from", "2").stderr
    assert "--probe refuted" in move("--confidence", "1", "--confidence-from", "4", *sentence).stderr
    refuted = move("--confidence", "1", "--confidence-from", "4", *sentence, "--probe", "refuted")
    assert refuted.returncode == 0 and json.loads(refuted.stdout)["probe"] == "refuted", refuted.stderr
    assert "--validation" in move("--confidence", "1", "--confidence-from", "4", "--probe", "refuted").stderr
    assert "cannot also raise" in move("--confidence", "4", "--confidence-from", "2", *sentence, "--probe", "refuted").stderr


def test_review_dir_prefers_a_writable_task_and_falls_back_to_a_named_temp_path(tmp: Path) -> None:
    """The task directory when writable (not in PR mode); else a temp path naming the repo, the reason on stderr."""
    from crew.review import review_workspace
    task = tmp / "task"
    task.mkdir()
    (task / ".task-id").write_text(json.dumps({"slug": "probe"}))
    chosen = review_workspace.review_dir(str(task), "probe", "self")
    assert str(chosen).startswith(str(task)) and chosen.is_dir() and not (chosen / ".write-probe").exists(), chosen
    review_workspace.claim(chosen, "self", "probe", str(task))
    record = json.loads((chosen / "run.json").read_text())
    assert (record["mode"], record["repo"], record["task_dir"]) == ("self", "probe", str(task)) and record["created"], record
    assert not (chosen / "paths.txt").exists()
    printed = run("review-dir", "--task-dir", str(task), "--repo", "probe")
    assert printed.returncode == 0 and printed.stdout.strip() and not printed.stderr.strip(), printed
    # The temp fallback is shared by every user of the machine, so its repo name is this run's own.
    temp_repo = f"probe-{os.getpid()}"
    assert str(task) not in str(review_workspace.review_dir(str(task), temp_repo, "pr")), "PR mode never uses the task directory"
    if os.geteuid() != 0:
        sealed = tmp / "sealed"
        sealed.mkdir()
        sealed.chmod(0o500)
        try:
            fallback = review_workspace.review_dir(str(sealed), temp_repo, "self")
        finally:
            sealed.chmod(0o700)
        assert str(sealed) not in str(fallback) and f"crew-review-{temp_repo}" in str(fallback) and fallback.is_dir(), fallback
        missing = run("review-dir", "--repo", f"{temp_repo}-unwritable", "--task-dir", "/nonexistent/task")
        assert missing.returncode == 0 and len(missing.stdout.strip().splitlines()) == 1 and "not writable" in missing.stderr, missing
    base = tmp / "prune"
    keep = base / "99999999999999"
    keep.mkdir(parents=True)
    for index in range(14):
        (base / f"202601010000{index:02d}").mkdir()
        (base / f"202601010000{index:02d}" / "artifact.json").write_text("{}")
    removed = review_workspace.cleanup_stale(base, keep)
    remaining = [p.name for p in base.iterdir()]
    assert len(removed) == 4 and len(remaining) == 11 and keep.name in remaining, remaining
