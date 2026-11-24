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


def test_a_nit_needs_a_comment_body_too(tmp: Path) -> None:
    """A nit is still a finding the author should see, so it is worded like any other.

    This test used to assert the opposite, and that assertion is what shipped a PR review with three
    nit findings, no `comments.md`, and no warning: `comments.md` is the deliverable, and the nits
    were the whole review.
    """
    directory = review_dir(tmp, [finding(label="nit", comment=None)])
    result = run("comments", "--review-dir", str(directory))
    assert result.returncode == 1, result.stdout
    assert "no comment drafted for 'Status is published twice'" in result.stderr, result.stderr
    assert not (directory / "comments.md").exists()


def test_a_nit_with_a_body_reaches_the_paste_ready_file(tmp: Path) -> None:
    """The positive control for the case above: one nit is enough to produce the file."""
    directory = review_dir(tmp, [finding(label="nit", comment="nit: could this reuse the helper?")])
    result = run("comments", "--review-dir", str(directory), "--head", "0ec93baa")
    assert result.returncode == 0, result.stderr
    text = (directory / "comments.md").read_text()
    assert "nit: could this reuse the helper?" in text
    assert "## 1. a.ts:12" in text
    assert json.loads(result.stdout)["drafted"] == 1


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


def test_persist_says_so_when_no_comment_was_drafted(tmp: Path) -> None:
    """A body-less PR review must not read as finished: the file is the deliverable."""
    directory = review_dir(tmp, [finding(comment=None)])
    report = tmp / "report.md"
    report.write_text("## Review: PR — one finding\n")
    result = run("persist", "--review-dir", str(directory), "--report", str(report),
                 "--findings", str(directory / "consolidation.json"), "--mode", "pr",
                 "--head", "0123456789abcdef0123456789abcdef01234567",
                 "--personas", "adversarial", "code-quality")
    assert result.returncode == 0, result.stderr
    assert "no comment drafted for 1 finding(s)" in result.stderr, result.stderr
    assert "no paste-ready comment exists" in result.stderr, result.stderr
    assert "comments --review-dir" in result.stderr, "the warning does not say how to finish"
    assert (directory / "REVIEW.md").is_file()
    assert not (directory / "comments.md").exists()


def test_a_concrete_fix_renders_a_github_suggestion_block(tmp: Path) -> None:
    """GitHub commits the lines in a bare ```suggestion fence, so the renderer owns the fence."""
    directory = review_dir(tmp, [
        finding(comment="This reads past the end when the list is empty.",
                suggestion="const first = rows[0] ?? null;"),
    ])
    result = run("comments", "--review-dir", str(directory))
    assert result.returncode == 0, result.stderr
    text = (directory / "comments.md").read_text()
    assert "```suggestion\nconst first = rows[0] ?? null;\n```" in text, text
    # The fence carries no info string; ```` ```ts suggestion ```` or ```` ``` suggestion ```` is not
    # a suggestion block to GitHub, and the author has to retype the change.
    assert "```suggestion" in text and "```ts" not in text, text


def test_the_suggestion_block_follows_the_prose(tmp: Path) -> None:
    """The body explains, then the block is the last thing: GitHub reads the fence from the body."""
    directory = review_dir(tmp, [finding(comment="Safer as ?? null.",
                                         suggestion="const first = rows[0] ?? null;")])
    run("comments", "--review-dir", str(directory))
    text = (directory / "comments.md").read_text()
    assert text.index("Safer as ?? null.") < text.index("```suggestion"), text


def test_a_finding_without_a_suggestion_renders_no_fence(tmp: Path) -> None:
    """A decision has no replacement to commit, so no empty fence is emitted for it."""
    directory = review_dir(tmp, [finding(comment="Your call which way the expected value moves.")])
    run("comments", "--review-dir", str(directory))
    text = (directory / "comments.md").read_text()
    assert "```suggestion" not in text, text


def test_blank_suggestion_lines_are_not_a_block(tmp: Path) -> None:
    """Whitespace is not a replacement; an empty fence would offer a one-click deletion."""
    directory = review_dir(tmp, [finding(comment="Something is wrong here.", suggestion="  \n\t\n")])
    run("comments", "--review-dir", str(directory))
    text = (directory / "comments.md").read_text()
    assert "```suggestion" not in text, text


def test_a_carried_suggestion_survives_a_merge(tmp: Path) -> None:
    """Two lenses flagging one defect: the one that supplied the code keeps it through the merge."""
    body = {
        "findings": [
            finding(comment="First lens.", suggestion="const first = rows[0] ?? null;"),
            finding(comment="Second lens."),
        ]
    }
    directory = review_dir(tmp, [])
    (directory / "consolidation.json").write_text(json.dumps(body))
    result = run("normalize", str(directory / "consolidation.json"),
                 "--output", str(directory / "merged.json"), "--lenient")
    assert result.returncode == 0, result.stderr
    merged = json.loads((directory / "merged.json").read_text())
    kept = [f for f in merged["findings"] if f.get("suggestion")]
    assert kept and kept[0]["suggestion"] == "const first = rows[0] ?? null;", merged


def test_a_suggestion_is_only_code(tmp: Path) -> None:
    """The field carries the replacement lines, so a fence or prose in it renders a broken block."""
    directory = review_dir(tmp, [
        finding(comment="Safer as ?? null.", suggestion="const first = rows[0] ?? null;"),
        finding(title="Second", file="b.ts", comment="Same shape here.",
                suggestion="```ts\nconst x = 1;\n```"),
    ])
    result = run("comments", "--review-dir", str(directory))
    assert result.returncode == 0, result.stderr
    text = (directory / "comments.md").read_text()
    assert "```ts" not in text, "a language tag inside `suggestion` would demote the block"
    assert text.count("```suggestion") == 2, text


def test_a_clean_review_writes_a_file_saying_so(tmp: Path) -> None:
    """No findings is a result: the report links this path, so the file must exist."""
    directory = review_dir(tmp, [])
    result = run("comments", "--review-dir", str(directory))
    assert result.returncode == 0, result.stderr
    assert (directory / "comments.md").is_file()
    text = (directory / "comments.md").read_text()
    assert "No comments were drafted for this review." in text, text
    assert json.loads(result.stdout)["drafted"] == 0


def test_a_clean_pr_review_still_writes_the_file(tmp: Path) -> None:
    """No findings is a result. Step 8 reports this path, so a clean review must produce the file."""
    directory = review_dir(tmp, [])
    report = tmp / "report.md"
    report.write_text("## Review: PR #1 — nothing to fix\n")
    result = run("persist", "--review-dir", str(directory), "--report", str(report),
                 "--findings", str(directory / "consolidation.json"), "--mode", "pr",
                 "--head", "0123456789abcdef0123456789abcdef01234567",
                 "--personas", "adversarial", "code-quality")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "comments" in payload, payload
    text = (directory / "comments.md").read_text()
    assert "No comments were drafted for this review." in text, text
    assert "no paste-ready comment exists" not in result.stderr, result.stderr


def test_findings_without_bodies_do_not_claim_a_clean_review(tmp: Path) -> None:
    """The opposite case: findings exist and are unworded, so "none drafted" would be a lie."""
    directory = review_dir(tmp, [finding(comment=None)])
    report = tmp / "report.md"
    report.write_text("## Review: PR #1 — one finding\n")
    result = run("persist", "--review-dir", str(directory), "--report", str(report),
                 "--findings", str(directory / "consolidation.json"), "--mode", "pr",
                 "--head", "0123456789abcdef0123456789abcdef01234567",
                 "--personas", "adversarial", "code-quality")
    assert result.returncode == 0, result.stderr
    assert "comments_missing" in json.loads(result.stdout), result.stdout
    assert not (directory / "comments.md").exists()
    assert "no paste-ready comment exists" in result.stderr, result.stderr


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
