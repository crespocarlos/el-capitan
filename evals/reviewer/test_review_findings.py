#!/usr/bin/env python3
"""Contract checks for .agent/tools/review-findings.py normalize and persist."""
from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "review-findings.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


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


def test_normalize_rejects_unknown_persona(tmp: Path) -> None:
    source = tmp / "bad.json"
    source.write_text(json.dumps([{"title": "x", "label": "nit", "persona": "nobody"}]))
    result = run("normalize", str(source))
    assert result.returncode == 2
    assert "unknown persona" in result.stderr


def test_normalize_accepts_legacy_persona(tmp: Path) -> None:
    source = tmp / "legacy.json"
    source.write_text(json.dumps([{"title": "x", "label": "nit", "persona": "Fresh Eyes"}]))
    result = run("normalize", str(source))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["findings"][0]["persona"] == ["fresh-eyes"]


def test_persist_writes_both_reports_and_appends_deferred(tmp: Path) -> None:
    task = tmp / "task"
    review_dir = task / "review" / "2026-10-30T12-00"
    report = tmp / "report.md"
    report.write_text("## Verdict: PASS\n")
    findings = tmp / "findings.json"
    findings.write_text(json.dumps([
        {"title": "Old flaky helper", "label": "attention", "file": "b.ts", "line": 4, "disposition": "defer"},
        {"title": "Rename var", "label": "nit", "disposition": "patch"},
    ]))
    # Persistence always names its personas and proves each one ran; a report with no
    # persona evidence is indistinguishable from a full review that skipped a lens.
    for persona in ("adversarial", "code-quality"):
        (review_dir / f"{persona}.in.md").parent.mkdir(parents=True, exist_ok=True)
        (review_dir / f"{persona}.in.md").write_text("in")
        (review_dir / f"{persona}.out.md").write_text("### Verdict: no findings\n")
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


def test_normalize_strict_requires_verified_evidence_and_cap(tmp: Path) -> None:
    source = tmp / "c.json"
    base = {"title": "t", "label": "attention", "file": "a.ts", "disposition": "patch"}
    source.write_text(json.dumps([base]))
    assert run("normalize", str(source), "--strict").returncode == 2
    assert run("normalize", str(source)).returncode == 0
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3",
                                   "validation": "read a.ts:1-9; the guard is absent"}]))
    assert run("normalize", str(source), "--strict").returncode == 0
    # `verified: true` claims a second read; strict now requires its conclusion too, so a bare
    # boolean cannot pass as evidence of one.
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3"}]))
    strict = run("normalize", str(source), "--strict")
    assert strict.returncode == 2 and "validation sentence" in strict.stderr
    # Without --strict it still normalizes, because older artifacts have no such field.
    assert run("normalize", str(source)).returncode == 0
    for evidence in (True, {}, "verified elsewhere", "a.ts"):
        source.write_text(json.dumps([{**base, "verified": True, "evidence": evidence,
                                       "validation": "read it"}]))
        assert run("normalize", str(source), "--strict").returncode == 2
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3@abc1234",
                                   "validation": "read it at the PR head"}]))
    assert run("normalize", str(source), "--strict").returncode == 0
    many = [{**base, "title": f"t{i}", "label": "nit"} for i in range(8)]
    source.write_text(json.dumps(many))
    result = run("normalize", str(source), "--strict")
    assert result.returncode == 2 and "cap" in result.stderr


def test_normalize_strict_caps_nits_separately_from_total(tmp: Path) -> None:
    source = tmp / "c.json"
    ok = {"verified": True, "evidence": "a.ts:3", "file": "a.ts", "disposition": "patch",
          "validation": "read a.ts:1-9"}

    def write(items: list[dict]) -> subprocess.CompletedProcess:
        source.write_text(json.dumps(items))
        return run("normalize", str(source), "--strict")

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
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    report = tmp / "report.md"
    report.write_text("## Verdict: PASS\n")
    findings = tmp / "findings.json"
    findings.write_text(json.dumps([
        {"title": "An unanchored nit", "label": "nit", "disposition": "patch"},
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
        findings.write_text(json.dumps([{"title": "probe", "label": "nit", "disposition": "patch", **extra}]))
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
        {"title": "An unverified attention finding", "label": "attention", "disposition": "patch"},
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
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    report = tmp / "report.md"

    def persist() -> subprocess.CompletedProcess:
        return run("persist", "--review-dir", str(review_dir), "--report", str(report),
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
        "## Review: changes\n\n1. [attention] **a.md — line 2** — the doc says\n\n"
        "```text\n### Files reviewed\n- a.ts\n```\n"
    )
    assert persist().returncode == 0, "a quoted heading was rejected as a duplicate section"
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
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report), "--strict", "--personas", "adversarial")
    result = run(*args)
    assert result.returncode == 2 and "adversarial.in.md" in result.stderr
    (review_dir / "adversarial.in.md").write_text("in")
    # A real persona artifact carries a verdict or a status line; a bare word with
    # neither is indistinguishable from a crashed run and must not pass the gate.
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    assert run(*args).returncode == 0
    comma_args = (
        "persist", "--review-dir", str(review_dir), "--report", str(report),
        "--strict", "--personas", "adversarial,code-quality",
    )
    result = run(*comma_args)
    assert result.returncode == 2 and "comma-separated personas" in result.stderr


def test_persist_strict_rejects_empty_persona_output(tmp: Path) -> None:
    """A persona that died before writing anything must not yield a persisted review."""
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    report = tmp / "report.md"
    report.write_text("x\n")
    for persona in ("adversarial", "code-quality"):
        (review_dir / f"{persona}.in.md").write_text("in")
        (review_dir / f"{persona}.out.md").write_text("")
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                 "--strict", "--personas", "adversarial", "code-quality")
    assert result.returncode == 2 and "no output" in result.stderr
    assert not (tmp / "task" / "REVIEW.md").exists()


def test_persist_strict_rejects_placeholder_persona_output(tmp: Path) -> None:
    """A stub with a plausible status word must not pass as a completed persona.

    2026-11-09: `status: dispatched` stubs survived `--strict` because any word was
    returned verbatim and only a fixed set of six was treated as unusable.
    """
    review_dir = tmp / "task" / "review" / "ts"
    review_dir.mkdir(parents=True)
    report = tmp / "report.md"
    report.write_text("x\n")
    for persona, body in {
        "adversarial": "### Verdict: no findings\n",
        "code-quality": "# code-quality raw response captured\nstatus: dispatched\n",
    }.items():
        (review_dir / f"{persona}.in.md").write_text("in")
        (review_dir / f"{persona}.out.md").write_text(body)
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                 "--strict", "--personas", "adversarial", "code-quality")
    assert result.returncode == 2 and "no output" in result.stderr, result.stdout + result.stderr
    assert not (tmp / "task" / "REVIEW.md").exists()
    # The same placeholder alone must fail too, and a real artifact must still pass.
    (review_dir / "adversarial.out.md").write_text("status: dispatched\n")
    assert run("persist", "--review-dir", str(review_dir), "--report", str(report),
               "--strict", "--personas", "adversarial").returncode == 2
    for persona in ("adversarial", "code-quality"):
        (review_dir / f"{persona}.out.md").write_text("### Verdict: no findings\n")
    assert run("persist", "--review-dir", str(review_dir), "--report", str(report),
               "--strict", "--personas", "adversarial", "code-quality").returncode == 0


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
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    report = tmp / "report.md"
    report.write_text("## Review: PR\n")
    absent = "0123456789abcdef0123456789abcdef01234567"
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report),
            "--mode", "pr", "--head", absent, "--personas", "adversarial")
    result = run(*args)
    assert result.returncode == 0, result.stderr
    assert f"Reviewed at: {absent}" in (task / "REVIEW.md").read_text()
    # Non-PR modes still reject a SHA the local repository cannot resolve.
    local = run("persist", "--review-dir", str(review_dir), "--report", str(report),
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
        # every persona: explicit no-findings verdict
        "verdict": "### Verdict: no findings\n",
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
    assert module.canonical_personas("adversarial code-quality".split(), split_commas=False) == [
        "adversarial", "code-quality"]


def test_select_returns_required_personas(tmp: Path) -> None:
    result = run("select", "--mode", "changes", "--contract",
                 "--paths", ".cursor/skills/x/SKILL.md", "rules/crew-router.mdc", "evals/a.json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["required"] == [
        "adversarial", "architecture", "code-quality", "product-flow", "prompt-quality"]
    assert json.loads(run("select", "--mode", "pr", "--paths", "x.ts").stdout)["required"] == ["adversarial", "code-quality"]
    assert "prompt-quality" in json.loads(
        run("select", "--mode", "changes", "--paths", "evals/reviewer/run.py").stdout
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
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    (task / "REVIEW.md").write_text("## Verdict: PASS\n")
    report = tmp / "report.md"
    report.write_text("## Review: Spec\n")
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report), "--mode", "spec",
                 "--personas", "adversarial")
    assert result.returncode == 0, result.stderr
    assert (task / "REVIEW.md").read_text() == "## Verdict: PASS\n"
    assert (task / "REVIEW.spec.md").read_text() == "## Review: Spec\n"


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
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report),
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
    # Without --strict a stray map is ignored, so plain callers never see the gate.
    plain = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                "--personas", "adversarial")
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
            "verified": True, "evidence": "a.ts:3", "validation": "read a.ts:1-9"}
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
            "validation": "read a.ts:1-9"}
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
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    (review_dir / "hunks.json").write_text(
        json.dumps({"files": [], "hunks": [{"id": "h1"}, {"id": "h2"}]}))
    (review_dir / "layers.json").write_text(json.dumps({"layers": [
        {"id": "L1", "title": "Contract", "explainer": "why", "reviewFocus": "- verify", "hunks": ["h1"]},
        {"id": "L2", "explainer": "why", "reviewFocus": "- verify", "hunks": ["h2"]},
    ]}))
    report = tmp / "report.md"
    report.write_text("## Review: changes\n")
    findings = tmp / "findings.json"
    findings.write_text(json.dumps([
        {"title": "Guard missing", "label": "attention", "disposition": "patch", "hunks": ["h1"],
         "verified": True, "evidence": "a.ts:3", "validation": "read a.ts:1-9"},
        {"title": "Rename", "label": "nit", "disposition": "patch"},
        {"title": "Old bug", "label": "attention", "disposition": "defer"},
    ]))
    args = ("persist", "--review-dir", str(review_dir), "--report", str(report),
            "--findings", str(findings), "--strict", "--personas", "adversarial")
    result = run(*args)
    assert result.returncode == 0, result.stderr
    written = (review_dir / "REVIEW.md").read_text()
    assert "### Coverage by layer" in written
    assert "- Contract (h1): [attention] Guard missing" in written
    assert "- L2 (h2): no findings" in written
    assert "- outside the map: [nit] Rename" in written
    assert "Old bug" not in written.split("### Coverage by layer", 1)[1]
    # The same gate rejects an emitted finding that cites a hunk outside the index.
    findings.write_text(json.dumps([
        {"title": "Ghost", "label": "attention", "disposition": "patch", "hunks": ["h7"]}]))
    blocked = run(*args)
    assert blocked.returncode == 2 and "unknown hunk" in blocked.stderr, blocked.stderr


def test_validate_map_reports_contract_errors_with_layer_index(tmp: Path) -> None:
    hunks, _ = write_map(tmp, ["h1", "h2"], [["h1"], ["h2"]])
    review = tmp / "review.json"
    review.write_text(json.dumps({
        "summary": "what happens",
        "risk": "high",
        "layers": [{"id": "L1", "explainer": "why", "reviewFocus": "- verify", "hunks": ["h1", "h9"]}],
        "concerns": [{"severity": "urgent", "title": "t", "detail": "d", "hunk": "h7"}],
    }))
    result = run("validate-map", "--review", str(review), "--hunks", str(hunks))
    assert result.returncode == 1
    assert "unknown hunk 'h9'" in result.stderr
    assert "h2" in result.stderr                      # reported as in no layer
    assert "concerns[1].severity" in result.stderr
    assert "concerns[1].hunk 'h7'" in result.stderr


def test_validate_map_accepts_a_complete_map(tmp: Path) -> None:
    hunks, _ = write_map(tmp, ["h1", "h2"], [["h1"], ["h2"]])
    review = tmp / "review.json"
    review.write_text(json.dumps({
        "summary": "what happens",
        "risk": "low",
        "layers": [
            {"id": "foundation", "kind": "foundation", "title": "types",
             "explainer": "why", "reviewFocus": "- look", "hunks": ["h1"]},
            {"id": "core", "title": "logic", "explainer": "why", "reviewFocus": "- check", "hunks": ["h2"],
             "hunkNotes": {"h2": "the fix"}},
        ],
        "concerns": [{"severity": "nit", "title": "t", "detail": "d", "hunk": "h2"}],
        "references": [{"title": "docs", "url": "https://example.invalid"}],
    }))
    result = run("validate-map", "--review", str(review), "--hunks", str(hunks))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_validate_map_requires_review_focus_and_at_most_eight_layers(tmp: Path) -> None:
    known = [f"h{index}" for index in range(1, 10)]
    hunks, _ = write_map(tmp, known, [[hunk] for hunk in known])
    review = tmp / "review.json"
    review.write_text(json.dumps({
        "summary": "what happens",
        "layers": [
            {"id": f"L{index}", "explainer": "why", "reviewFocus": "- verify", "hunks": [hunk]}
            for index, hunk in enumerate(known, 1)
        ],
    }))
    result = run("validate-map", "--review", str(review), "--hunks", str(hunks))
    assert result.returncode == 1 and "exceeds the maximum of 8" in result.stderr, result.stderr

    review.write_text(json.dumps({
        "summary": "what happens",
        "layers": [{"id": "L1", "explainer": "why", "hunks": known}],
    }))
    result = run("validate-map", "--review", str(review), "--hunks", str(hunks))
    assert result.returncode == 1 and "reviewFocus is missing" in result.stderr, result.stderr


def test_validate_map_rejects_a_note_for_a_foreign_hunk(tmp: Path) -> None:
    """A hunkNotes entry must belong to the layer that carries it, or the note is unreachable."""
    hunks, _ = write_map(tmp, ["h1", "h2"], [["h1"], ["h2"]])
    review = tmp / "review.json"
    review.write_text(json.dumps({
        "summary": "s",
        "layers": [{"id": "L1", "explainer": "e", "hunks": ["h1"], "hunkNotes": {"h2": "note"}}],
    }))
    result = run("validate-map", "--review", str(review), "--hunks", str(hunks))
    assert result.returncode == 1 and "not in its hunks" in result.stderr, result.stderr


def test_validate_map_accepts_a_note_for_its_own_hunk(tmp: Path) -> None:
    hunks, _ = write_map(tmp, ["h1", "h2"], [["h1"], ["h2"]])
    review = tmp / "review.json"
    review.write_text(json.dumps({
        "summary": "s",
        "layers": [{"id": "L1", "explainer": "e", "reviewFocus": "- verify", "hunks": ["h1", "h2"],
                    "hunkNotes": {"h2": "note"}}],
    }))
    result = run("validate-map", "--review", str(review), "--hunks", str(hunks))
    assert result.returncode == 0, result.stderr


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


def write_packages(tmp: Path, packages: dict[str, str]) -> Path:
    task = tmp / "task"
    review_dir = task / "review" / "20261118150000"
    review_dir.mkdir(parents=True)
    (task / "SPEC.md").write_text(SPEC)
    for persona, text in packages.items():
        (review_dir / f"{persona}.in.md").write_text(text)
    return review_dir


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
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    report = tmp / "report.md"
    report.write_text("## Verdict: PASS\n")
    persist = ("persist", "--review-dir", str(review_dir), "--report", str(report), "--strict",
               "--personas", "adversarial")
    # A directory packaged before package.diff existed is not held to the package rules.
    assert run(*persist).returncode == 0
    (review_dir / "package.diff").write_text("")
    strict = run(*persist)
    assert strict.returncode == 2 and "generated file yarn.lock" in strict.stderr
    collapsed = lock.split("@@")[0] + "# yarn.lock: likely generated, +1/-1 lines omitted (h1)\n"
    (review_dir / "adversarial.in.md").write_text(collapsed)
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


def test_findings_outrank_a_trailing_no_findings_verdict(tmp: Path) -> None:
    """A persona emitted anchored findings and then `### Verdict: no findings`.

    Content wins: the verdict line means "nothing to report", never "discard what is above", so the
    artifact stays a completed run and the contradiction is noted rather than resolved by throwing
    evidence away.
    """
    both = ("1. [blocking] **`x-pack/a.ts — line 12`** (h3) — the guard is inverted\n\n"
            "```ts\nif (!ready) return;\n```\n\nIt rejects the ready path.\n\n"
            "Fix: flip the condition.\n\n### Verdict: no findings\n")
    assert classify(both) == "ok"
    # The other direction still holds, so the rule did not become permissive: a bare verdict is a
    # complete empty review, and a placeholder is still unknown.
    assert classify("### Verdict: no findings\n") == "ok"
    assert classify("status: dispatched\n\nraw response captured\n") == "unknown"


def test_kind_is_validated_normalized_and_absent_legal(tmp: Path) -> None:
    """The `kind` field's three rules, none of which had a test.

    Absent must pass (every recorded review predates the field), padding and case are normalized
    rather than rejected, a typo is refused, and `kind` stays out of the fingerprint so re-classifying
    a finding cannot create a second one.
    """
    source = tmp / "c.json"
    base = {"title": "t", "label": "attention", "file": "a.ts", "disposition": "patch"}

    def normalize(payload: list[dict]) -> subprocess.CompletedProcess:
        source.write_text(json.dumps(payload))
        return run("normalize", str(source))

    assert normalize([base]).returncode == 0, "an absent kind is legal"
    padded = normalize([{**base, "kind": "  Security "}])
    assert padded.returncode == 0
    assert json.loads(padded.stdout)["findings"][0]["kind"] == "security"
    typo = normalize([{**base, "kind": "securty"}])
    assert typo.returncode == 2 and "invalid kind" in typo.stderr
    # Identity is the defect, not its classification: same file, label and title means one finding.
    plain = json.loads(normalize([base]).stdout)["findings"][0]["fingerprint"]
    classified = json.loads(normalize([{**base, "kind": "security"}]).stdout)["findings"][0]["fingerprint"]
    assert plain == classified


def test_near_duplicates_pin_both_threshold_edges(tmp: Path) -> None:
    """Above the threshold appears, below it does not, and a blank file never pairs.

    The earlier version of this test passed with any threshold from 0.01 to 0.77, so the measured
    value its comment rests on was unverified. These titles are constructed to sit either side of 0.2
    and at 0.5-overlap for the unfiled case.
    """
    source = tmp / "c.json"
    base = {"label": "attention", "file": "a.yaml", "disposition": "patch"}
    # Four shared tokens of five total -> 0.8, comfortably above.
    source.write_text(json.dumps([
        {**base, "title": "resolver falls back to empty list instead of reported rules"},
        {**base, "title": "resolver falls back to empty list ignoring reported rules"},
        # Shared tokens below the threshold: one common token of many distinct ones.
        {**base, "title": "schema description claims stamps that never succeeded"},
    ]))
    payload = json.loads(run("normalize", str(source)).stdout)
    assert len(payload["findings"]) == 3, "a candidate pair must never be merged"
    assert len(payload["merge_candidates"]) == 1
    assert payload["merge_candidates"][0]["similarity"] >= 0.2
    assert "schema" not in payload["merge_candidates"][0]["titles"][0]
    # Two unfiled findings with similar titles must not pair: no file means no shared subject.
    source.write_text(json.dumps([
        {"label": "nit", "disposition": "patch", "title": "rename the helper for clarity"},
        {"label": "nit", "disposition": "patch", "title": "rename the helper for readability"},
    ]))
    assert json.loads(run("normalize", str(source)).stdout)["merge_candidates"] == []


def test_persist_places_confidence_under_the_verdict(tmp: Path) -> None:
    """The line goes below the verdict, not at the end — and a report carrying one is refused."""
    task = tmp / "task"
    review_dir = task / "review" / "20260101000000"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("package")
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    (review_dir / "layers.json").write_text(json.dumps(
        {"layers": [{"id": "L1", "kind": "core", "title": "t", "explainer": "e",
                     "reviewFocus": "- f", "hunks": ["h1"]}]}))
    (review_dir / "hunks.json").write_text(json.dumps({"files": [], "hunks": [{"id": "h1"}]}))
    report = tmp / "report.md"
    args = ["persist", "--review-dir", str(review_dir), "--report", str(report), "--mode", "changes",
            "--personas", "adversarial", "--strict", "--confidence", "40",
            "--confidence-reason", "the diff was read"]
    report.write_text("## Review: changes — x\n\nVerdict: PASS\n\n1. [nit] stuff\n")
    assert run(*args).returncode == 0
    written = (review_dir / "REVIEW.md").read_text()
    assert written.index("Confidence:") < written.index("### Coverage by layer"), written
    assert written.index("Verdict: PASS") < written.index("Confidence:")
    # A hand-written copy is refused rather than duplicated.
    report.write_text("## Review: changes — x\n\nVerdict: PASS\n\nConfidence: 90% — invented\n")
    refused = run(*args)
    assert refused.returncode == 2 and "already carries a `Confidence:` line" in refused.stderr



    """Two reviewers state one defect differently; both stay, the pair is reported with a score.

    The threshold is measured low (0.2) because title overlap cannot separate a real duplicate from a
    coincidence: over 81 recorded reviews the maximum same-file overlap was 0.33. So this reports a
    candidate, never a merge — a wrong merge deletes a finding.
    """
    source = tmp / "c.json"
    base = {"label": "attention", "file": "a.yaml", "disposition": "patch",
            "verified": True, "evidence": "a.yaml:3", "validation": "read a.yaml"}
    source.write_text(json.dumps([
        {**base, "title": "resolver falls back to an empty list instead of reported rules"},
        {**base, "title": "resolver falls back to an empty list, dropping reported rules"},
        {**base, "title": "schema description claims stamps that never succeeded"},
    ]))
    payload = json.loads(run("normalize", str(source), "--strict").stdout)
    assert len(payload["findings"]) == 3, "a candidate pair must not be merged"
    assert payload["duplicates"] == []
    assert len(payload["merge_candidates"]) == 1
    pair = payload["merge_candidates"][0]
    assert pair["similarity"] >= 0.2 and pair["files"] == ["a.yaml", "a.yaml"]
    # Different files never pair, however similar the titles.
    source.write_text(json.dumps([
        {**base, "title": "resolver falls back to an empty list instead of reported rules"},
        {**base, "title": "resolver falls back to an empty list instead of reported rules",
         "file": "b.yaml"},
    ]))
    assert json.loads(run("normalize", str(source), "--strict").stdout)["merge_candidates"] == []


def test_persist_renders_confidence_and_requires_a_reason(tmp: Path) -> None:
    """Confidence sits under the verdict and is optional; a bare number is refused."""
    task = tmp / "task"
    review_dir = task / "review" / "20260101000000"
    review_dir.mkdir(parents=True)
    (review_dir / "adversarial.in.md").write_text("package")
    (review_dir / "adversarial.out.md").write_text("### Verdict: no findings\n")
    report = tmp / "report.md"
    base = ["persist", "--review-dir", str(review_dir), "--report", str(report),
            "--mode", "changes", "--personas", "adversarial"]
    report.write_text("## Review: changes — nothing\n")
    assert run(*base).returncode == 0
    assert "Confidence:" not in (review_dir / "REVIEW.md").read_text(), "omitting it is valid"
    report.write_text("## Review: changes — nothing\n")
    assert run(*base, "--confidence", "30").returncode == 2, "a percentage needs its reason"
    report.write_text("## Review: changes — nothing\n")
    assert run(*base, "--confidence", "101", "--confidence-reason", "x").returncode == 2
    report.write_text("## Review: changes — nothing\n")
    assert run(*base, "--confidence", "30", "--confidence-reason",
               "the diff was read; no test was run").returncode == 0
    assert "Confidence: 30% — the diff was read; no test was run" in (review_dir / "REVIEW.md").read_text()


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                test(Path(tmp))
                print(f"pass: {test.__name__}")
            except AssertionError as error:
                failed += 1
                print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
