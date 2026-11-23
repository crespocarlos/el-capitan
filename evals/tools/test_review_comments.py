#!/usr/bin/env python3
"""Paste-ready review comments, dropped-finding records, and the layer-reply parse gate.

Three gaps this suite pins, all from one measured PR review:

- The protocol ended at `report.md`, so turning findings into comments on someone else's PR meant
  hand assembly: re-wording each one, choosing the anchor, and re-deciding that posting is external
  state. `comments.md` now carries one body per anchor and never posts.
- Three legitimate nits were dropped to stay inside the nit budget and left no artifact, so a
  reviewer could not tell whether theirs had been seen. `dropped` now lands in `DROPPED.md`.
- `reviewer-layers` emitted a stray comma inside its fenced block; coverage only failed later, or
  not at all when the block was hand-repaired before writing. `check-map` parses it first.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "review" / "crew-review-findings.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


def finding(**overrides: object) -> dict:
    """A verified attention finding at a PR head, with the excerpt the PR-head gate requires."""
    record = {"title": "Status is published twice", "label": "attention", "file": "a.ts", "line": 12,
              "disposition": "patch", "kind": "correctness", "confidence": 4,
              "verified": True, "evidence": "a.ts:12@0ec93ba",
              "validation": "read a.ts:10-20; both branches call publish",
              "excerpt": "if (changed) {\n  publish(event);\n}"}
    for key, value in overrides.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    return record


def review_dir(tmp: Path, findings: list[dict]) -> Path:
    """A PR-shaped review directory: personas present, findings consolidated, no SPEC.md."""
    directory = tmp / "review-root" / "review" / "ts"
    directory.mkdir(parents=True)
    for persona in ("adversarial", "code-quality"):
        (directory / f"{persona}.in.md").write_text("in")
        (directory / f"{persona}.out.md").write_text("### Verdict: no findings\n")
    (directory / "consolidation.json").write_text(json.dumps({"findings": findings}))
    return directory


def test_comments_are_drafted_per_anchor_and_never_posted(tmp: Path) -> None:
    """Each emitted comment becomes one section; the draft says nothing was posted."""
    body = "Does this publish twice when the status is already set?"
    directory = review_dir(tmp, [
        finding(comment=body),
        finding(title="Silent skip", file="b.ts", line=4, label="blocking",
                evidence="b.ts:4@0ec93ba", comment="This drops the event when the rule is gone."),
    ])
    result = run("comments", "--review-dir", str(directory), "--head", "0ec93baa")
    assert result.returncode == 0, result.stderr
    text = (directory / "comments.md").read_text()
    assert body in text
    assert "## 1. a.ts:12" in text and "## 2. b.ts:4" in text, text
    assert "nothing here was posted" in text
    assert "Reviewed at: 0ec93baa" in text
    # The verified lines travel with the comment, so the paste needs no second lookup.
    assert "publish(event);" in text
    assert json.loads(result.stdout)["drafted"] == 2


def test_a_missing_comment_body_fails_the_comments_command(tmp: Path) -> None:
    """A finding with no drafted wording is named, and no partial file is written."""
    directory = review_dir(tmp, [finding(comment=None)])
    result = run("comments", "--review-dir", str(directory))
    assert result.returncode == 1
    assert "no comment drafted for 'Status is published twice'" in result.stderr, result.stderr
    assert not (directory / "comments.md").exists()


def test_a_nit_needs_no_comment_body(tmp: Path) -> None:
    """A nit is polish the author may ignore, so it does not have to be worded for the PR."""
    directory = review_dir(tmp, [finding(label="nit", comment=None)])
    result = run("comments", "--review-dir", str(directory))
    assert result.returncode == 0, result.stderr


def test_persist_drafts_comments_for_a_pr_review(tmp: Path) -> None:
    """A PR review writes comments.md beside its report, and a self-review does not."""
    directory = review_dir(tmp, [finding(comment="Does this publish twice?")])
    report = tmp / "report.md"
    report.write_text("## Review: PR — one finding\n")
    result = run("persist", "--review-dir", str(directory), "--report", str(report),
                 "--findings", str(directory / "consolidation.json"), "--mode", "pr",
                 "--head", "0123456789abcdef0123456789abcdef01234567",
                 "--personas", "adversarial", "code-quality")
    assert result.returncode == 0, result.stderr
    assert (directory / "comments.md").is_file()
    assert json.loads(result.stdout)["comments"].endswith("comments.md")


def test_persist_warns_rather_than_failing_on_an_undrafted_comment(tmp: Path) -> None:
    """The report is already valid, so a missing body is named on stderr and nothing else is lost."""
    directory = review_dir(tmp, [finding(comment=None)])
    report = tmp / "report.md"
    report.write_text("## Review: PR — one finding\n")
    result = run("persist", "--review-dir", str(directory), "--report", str(report),
                 "--findings", str(directory / "consolidation.json"), "--mode", "pr",
                 "--head", "0123456789abcdef0123456789abcdef01234567",
                 "--personas", "adversarial", "code-quality")
    assert result.returncode == 0, result.stderr
    assert "no comment drafted for 1 finding(s)" in result.stderr, result.stderr
    assert (directory / "REVIEW.md").is_file()
    assert not (directory / "comments.md").exists()


def test_dropped_findings_are_recorded_not_lost(tmp: Path) -> None:
    """A finding cut in consolidation lands in DROPPED.md, apart from the deferred list."""
    directory = review_dir(tmp, [
        finding(title="Deferred thing", label="attention", disposition="defer"),
        finding(title="Cut nit", label="nit", disposition="dropped", comment=None,
                reason="budget: 12 candidates for 4 slots"),
    ])
    report = tmp / "report.md"
    report.write_text("## Review: PR — one finding\n")
    result = run("persist", "--review-dir", str(directory), "--report", str(report),
                 "--findings", str(directory / "consolidation.json"), "--mode", "pr",
                 "--head", "0123456789abcdef0123456789abcdef01234567",
                 "--personas", "adversarial", "code-quality")
    assert result.returncode == 0, result.stderr
    owner = directory.parent.parent
    dropped = (owner / "DROPPED.md").read_text()
    assert "Cut nit" in dropped and "budget: 12 candidates for 4 slots" in dropped
    deferred = (owner / "DEFERRED.md").read_text()
    assert "Deferred thing" in deferred
    assert "Cut nit" not in deferred
    payload = json.loads(result.stdout)
    assert payload["dropped"] == 1 and payload["deferred"] == 1


def test_check_map_rejects_a_malformed_block_before_packaging(tmp: Path) -> None:
    """A stray comma is a parse error at the reply, not a coverage failure after every persona ran."""
    reply = tmp / "layers.reply.md"
    reply.write_text(
        "```json\n"
        '{"layers": [{"id": "a", "kind": "core", "title": "t", "explainer": "e",\n'
        '  "reviewFocus": "- f", "hunks": ["h1"],},]}\n'
        "```\n"
    )
    result = run("check-map", str(reply))
    assert result.returncode == 2
    assert "not valid JSON" in result.stderr, result.stderr


def test_check_map_rejects_the_wrong_number_of_blocks(tmp: Path) -> None:
    reply = tmp / "layers.reply.md"
    reply.write_text('```json\n{"layers": []}\n```\n\n```json\n{"layers": []}\n```\n')
    result = run("check-map", str(reply))
    assert result.returncode == 2 and "2 fenced json blocks" in result.stderr, result.stderr


def test_check_map_writes_the_parsed_map(tmp: Path) -> None:
    reply = tmp / "layers.reply.md"
    reply.write_text(
        "Here is the map.\n\n```json\n"
        '{"layers": [{"id": "a", "kind": "core", "title": "t", "explainer": "e",\n'
        '  "reviewFocus": "- f", "hunks": ["h1", "h2"], "hunkNotes": {"h2": "the fix"}}]}\n'
        "```\n"
    )
    out = tmp / "layers.json"
    result = run("check-map", str(reply), "--output", str(out))
    assert result.returncode == 0, result.stderr
    written = json.loads(out.read_text())
    assert written["layers"][0]["hunkNotes"] == {"h2": "the fix"}
    assert json.loads(result.stdout)["layers"] == 1


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                test(Path(directory))
                print(f"pass: {test.__name__}")
            except AssertionError as error:
                failures += 1
                print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
