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
    for _ in range(2):
        result = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                     "--findings", str(findings), "--files", "b.ts")
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
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3"}]))
    assert run("normalize", str(source), "--strict").returncode == 0
    for evidence in (True, {}, "verified elsewhere", "a.ts"):
        source.write_text(json.dumps([{**base, "verified": True, "evidence": evidence}]))
        assert run("normalize", str(source), "--strict").returncode == 2
    source.write_text(json.dumps([{**base, "verified": True, "evidence": "a.ts:3@abc1234"}]))
    assert run("normalize", str(source), "--strict").returncode == 0
    many = [{**base, "title": f"t{i}", "label": "nit"} for i in range(8)]
    source.write_text(json.dumps(many))
    result = run("normalize", str(source), "--strict")
    assert result.returncode == 2 and "cap" in result.stderr


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
    report = tmp / "report.md"
    report.write_text("## Review: PR\n")
    absent = "0123456789abcdef0123456789abcdef01234567"
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                 "--mode", "pr", "--head", absent)
    assert result.returncode == 0, result.stderr
    assert f"Reviewed at: {absent}" in (task / "REVIEW.md").read_text()
    # Non-PR modes still reject a SHA the local repository cannot resolve.
    local = run("persist", "--review-dir", str(review_dir), "--report", str(report),
                "--mode", "self", "--head", absent)
    assert local.returncode == 2 and "is not a commit" in local.stderr


def test_persist_pr_mode_requires_a_head_sha(tmp: Path) -> None:
    review_dir = tmp / "review-root" / "review" / "ts"
    review_dir.mkdir(parents=True)
    report = tmp / "report.md"
    report.write_text("## Review: PR\n")
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report), "--mode", "pr")
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
                 "--mode", "pr", "--head", "0123456789abcdef0123456789abcdef01234567")
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
    for name, body in accepted.items():
        path = tmp / f"{name}.out.md"
        path.write_text(body)
        assert module.persona_outcome(path) == "ok", name
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
    (task / "REVIEW.md").write_text("## Verdict: PASS\n")
    report = tmp / "report.md"
    report.write_text("## Review: Spec\n")
    result = run("persist", "--review-dir", str(review_dir), "--report", str(report), "--mode", "spec")
    assert result.returncode == 0, result.stderr
    assert (task / "REVIEW.md").read_text() == "## Verdict: PASS\n"
    assert (task / "REVIEW.spec.md").read_text() == "## Review: Spec\n"


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
