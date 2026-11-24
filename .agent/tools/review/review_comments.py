#!/usr/bin/env python3
"""Paste-ready review comments: one body per anchor, in the reviewer's own voice.

A PR review ends at `report.md`, which is a report for the reader who ran the review. Turning it
into comments on someone else's PR happened by hand: re-reading each finding, re-wording it into the
repository owner's voice, choosing the anchor, and remembering that posting is external state. The
mechanical half lives here so only the wording is written: the anchor, the ordering, the file, and
the refusal when a comment is missing.

Posting stays out of scope. `comments.md` is a draft, and nothing here calls `gh`.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lib.files import atomic_write
from review_models import ABSENT, Finding, read_json_object, to_finding
from review_render import label_with_score

# A PR comment is how a finding reaches the author, so every emitted label needs one — a nit
# included. Excluding nits produced a PR review with three findings, no `comments.md`, and no
# warning: the file is what the user pastes, and the nits were the whole review.
COMMENTED_LABELS = frozenset({"blocking", "attention", "needs more info", "nit"})
FENCE = "```"


def anchor(finding: Finding) -> str:
    """The `path:line` a comment attaches to, or "" when the finding has no usable anchor."""
    path = finding.text("file").strip()
    line = finding.text("line").strip()
    if not path:
        return ""
    return f"{path}:{line}" if line else path


def comment_body(finding: Finding) -> str:
    """The body written for this finding, or "" when the orchestrator wrote none."""
    return "" if finding.comment is ABSENT else str(finding.comment or "").strip()


def suggestion_block(finding: Finding) -> str:
    """The replacement code as a GitHub ```` ```suggestion ```` block, or "" when there is none.

    The fence carries no info string: GitHub turns a bare ```` ```suggestion ```` block into a
    one-click commit of the anchored range, so any other token silently demotes it to a plain code
    block. A writer that supplied its own fence — the common mistake, since the prose asks for one —
    is unwrapped here rather than rendered inside a second fence.
    """
    body = "" if finding.suggestion is ABSENT else str(finding.suggestion or "")
    body = body.strip("\n")
    if body.lstrip().startswith(FENCE) and body.rstrip().endswith(FENCE):
        inner = body.lstrip()[len(FENCE):]
        body = inner[:inner.rindex(FENCE)]
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.strip("\n")
    if not body.strip():
        return ""
    return f"{FENCE}suggestion\n{body}\n{FENCE}"


def missing_comments(findings: list[Finding], mode: str) -> list[str]:
    """Titles of emitted findings that still need a comment body, in report order.

    Only PR mode is gated: a self-review's findings are read by the person who ran it, so demanding
    a second wording there would be a copy of the same text with no reader.
    """
    if mode != "pr":
        return []
    return [f.title for f in findings
            if f.is_emitted() and f.label in COMMENTED_LABELS and not comment_body(f)]


def render(findings: list[Finding], head: str = "") -> str:
    """`comments.md`: one section per comment, in report order, each ready to paste.

    Order is the report's, so a reviewer pastes in the order they wrote the review. Nothing is
    repeated from the report's prose: the body is the whole comment, because the author of the PR
    reads one comment at a time and never sees this file.
    """
    lines = [
        "# Review comments",
        "",
        "One body per anchor, in the order of `report.md`. Paste each under its own line; nothing "
        "here was posted. A body ending in a GitHub suggestion block is a one-click commit of the "
        "anchored range.",
        "",
    ]
    if head:
        lines += [f"Reviewed at: {head}", ""]
    drafted = [f for f in findings if f.is_emitted() and comment_body(f)]
    if not drafted:
        return "\n".join(lines + ["No comments were drafted for this review.", ""])
    for index, finding in enumerate(drafted, 1):
        lines += [
            f"## {index}. {anchor(finding) or 'no anchor'}",
            "",
            f"_{label_with_score(finding)} {finding.title}_",
            "",
            comment_body(finding),
            "",
        ]
        replacement = suggestion_block(finding)
        if replacement:
            # The block goes inside the body, last: a suggestion is the actionable half of the
            # comment, and GitHub reads it from the comment text rather than from this file.
            lines += [replacement, ""]
        excerpt = finding.text("excerpt").strip()
        if excerpt:
            lines += ["Verified lines:", "", FENCE, excerpt, FENCE, ""]
        lines += ["---", ""]
    return "\n".join(lines)


def write_for_mode(review_dir: Path, findings: list[Finding], mode: str,
                   head: str = "") -> Path | None:
    """Write `comments.md` for a PR review; None when a PR review exists but worded nothing.

    Three cases, and the file matters in two of them. A clean review — no emitted finding at all —
    still gets the file, saying so, because Step 8 reports its path and a report linking a file that
    was never written is the defect this distinction closes. Emitted findings with bodies get the
    file. Emitted findings with no bodies get a warning and no file: a file saying "no comments were
    drafted" would misreport findings that exist but were never worded.
    """
    if mode != "pr":
        return None
    pending = missing_comments(findings, mode)
    if pending:
        print(f"warning: no comment drafted for {len(pending)} finding(s): "
              f"{'; '.join(pending)}", file=sys.stderr)
    if not any(f.is_emitted() for f in findings):
        return write(review_dir, findings, head)
    if not any(f.is_emitted() and comment_body(f) for f in findings):
        print("warning: no paste-ready comment exists for this PR review; add a `comment` body to "
              "each finding, then re-run `crew-review-findings.py comments --review-dir "
              f"{review_dir}`", file=sys.stderr)
        return None
    return write(review_dir, findings, head)


def write(review_dir: Path, findings: list[Finding], head: str = "") -> Path:
    """Write `comments.md` beside the report, returning the path."""
    path = review_dir / "comments.md"
    atomic_write(path, render(findings, head))
    return path


def findings_from(path: Path) -> list[Finding]:
    """Emitted findings from a written findings file, for a caller re-rendering comments later."""
    payload = read_json_object(path, "findings")
    return [to_finding(item, index) for index, item in enumerate(payload["findings"], 1)]
