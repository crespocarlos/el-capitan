#!/usr/bin/env python3
"""Anchors outside the diff: a docs or test file the change did not touch can still carry a finding.

`normalize --files` refuses evidence outside the reviewed set, which was right for a hunk anchor and
wrong for a finding about a doc that went stale or a test that no longer covers the change. With
`--repo` (and `--head`), a path outside the set is accepted when it is a TRACKED file at the reviewed
head; the finding is marked `anchor: "non-hunk"` (no hunk id is expected for it), and a `[blocking]`
one also needs `line_read: true`, the persona's statement that it read the cited line at that head.
An untracked path is still refused: an invented file must not pass as evidence.
"""
from __future__ import annotations

from pathlib import Path

from lib.git import GitError, output
from review_gates import is_path_prefix
from review_models import Finding

NON_HUNK = "non-hunk"


def is_non_hunk(finding: Finding) -> bool:
    return finding.extra.get("anchor") == NON_HUNK


def strip_markers(findings: list[Finding]) -> None:
    """Drop any incoming `anchor`: only `mark_outside` may set it, so a hand-set marker skips no rule."""
    for finding in findings:
        finding.extra.pop("anchor", None)


def evidence_path(finding: Finding) -> str:
    evidence = finding.text("evidence")
    return evidence.split("@", 1)[0].rsplit(":", 1)[0] if evidence else ""


def tracked_at(repo: Path, head: str) -> set[str]:
    try:
        return set(output(repo, ["ls-tree", "-r", "--name-only", head or "HEAD"]).splitlines())
    except GitError as error:
        raise ValueError(f"cannot list tracked files at {head or 'HEAD'}: {error}") from error


def mark_outside(findings: list[Finding], files: list[str], repo: Path, head: str) -> list[str]:
    """Mark each emitted finding anchored outside `files`; return their paths."""
    outside = [(f, evidence_path(f)) for f in findings if f.is_emitted()]
    outside = [(f, path) for f, path in outside if path and not any(is_path_prefix(n, path) for n in files)]
    if not outside:
        return []
    tracked = tracked_at(repo, head)
    for finding, path in outside:
        if path not in tracked:
            raise ValueError(f"finding {finding.title!r} cites {path}, which is not in the reviewed file set "
                             f"and not a tracked file at {head or 'HEAD'}")
        if finding.label == "blocking" and finding.extra.get("line_read") is not True:
            raise ValueError(f"blocking finding {finding.title!r} anchors outside the diff at {path}; "
                             "set line_read=true only after reading the cited line at the reviewed head, "
                             "or lower the label")
        finding.extra["anchor"] = NON_HUNK
    return sorted({path for _, path in outside})
