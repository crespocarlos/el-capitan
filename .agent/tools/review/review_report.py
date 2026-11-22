#!/usr/bin/env python3
"""Assembling a persisted review report: the gates, the sections it appends, and its identity.

`persist` writes the consolidated report to the review directory and the task-level REVIEW file,
appends deferred findings, and enforces the persona and layer gates. Three things it does are worth
keeping in one place: the two generated sections are derived from `--findings` and `--files` so a
report carrying its own copy would render the table twice; a missing layer map is written into the
report rather than only to stderr, because stderr is invisible in the artifact; and the reviewed
commit is recorded, so a review of a different tree is detectable later.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib.files import atomic_write
from lib.git import GitError, rev_parse
from review_findings import (
    CODE_MODES,
    Finding,
    canonical_personas,
    check_findings,
    check_strict,
    read_findings,
)
from review_personas import GENERATED_SECTIONS
from review_persist_gates import check_personas_present, strict_gates
from review_workspace import record_task_review


def heading_lines(text: str) -> set[str]:
    """The level-3 heading lines of a report, ignoring fenced blocks.

    A finding may quote a heading verbatim (the contract requires quoting, not paraphrasing), and a
    sub-heading such as `#### Files reviewed` is a different section. Only an exact level-3 heading
    outside a fence means the caller wrote the generated section themselves.
    """
    headings: set[str] = set()
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("### "):
            headings.add(line.rstrip())
    return headings


def validate_review_dir(args: argparse.Namespace) -> Path:
    """Resolve `--review-dir` and return the task directory it belongs to."""
    args.review_dir = args.review_dir.resolve()
    if args.review_dir.parent.name != "review":
        raise ValueError(f"--review-dir must be <task>/review/<timestamp>, got {args.review_dir}")
    owner = args.review_dir.parent.parent
    if args.mode == "pr" and not args.head.strip():
        raise ValueError("--mode pr requires --head with the reviewed GitHub SHA")
    if args.mode == "pr" and (owner / "SPEC.md").is_file():
        raise ValueError(
            "PR reviews must persist outside task state; use /tmp/crew-review-<repo>/review/<timestamp>"
        )
    return owner


def reviewed_at(args: argparse.Namespace, report: str) -> str:
    """Append the reviewed commit and return the report, after checking the SHA is real.

    `crew commit` moves HEAD past the reviewed tree, so the gate downstream accepts an ancestor;
    recording the SHA still makes a review of a *different* tree detectable. PR mode is the
    exception: the reviewed tree is the GitHub head and the local checkout never fetches it, so a
    local existence check would reject every PR review.
    """
    if not args.head:
        return report
    head = args.head.strip()
    if not re.fullmatch(r"[0-9a-f]{7,40}", head):
        raise ValueError(f"--head must be a commit SHA, got {head!r}")
    if args.mode != "pr":
        try:
            rev_parse(None, f"{head}^{{commit}}")
        except GitError:
            raise ValueError(f"--head {head} is not a commit in this repository") from None
    return report.rstrip() + f"\n\nReviewed at: {head}\n"


def append_deferred(owner: Path, rows: list[Finding]) -> None:
    """Append each deferred finding to DEFERRED.md, skipping one already recorded."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = owner / "DEFERRED.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    with path.open("a", encoding="utf-8") as handle:
        for f in rows:
            where = f"{f.text('file')}:{f.text('line')}".strip(":")
            reason = f.text("reason") or "pre-existing or out of scope"
            if f"[{f.label}] {f.title} — `{where}`" in existing:
                continue
            handle.write(f"- [{stamp}] [{f.label}] {f.title} — `{where}` — {reason}\n")


def persist(args: argparse.Namespace) -> int:
    """Write the report, the coverage section, and the deferred findings, after every gate."""
    owner = validate_review_dir(args)
    findings = read_findings(args.findings) if args.findings else []
    check_personas_present(args)
    coverage_section = coverage_gap = ""
    if args.strict:
        coverage_section, coverage_gap = strict_gates(args, owner, findings)
    report = args.report.read_text(encoding="utf-8")
    # The two generated sections are derived from --findings and --files, so a report carrying its
    # own copy would render the table twice and a reader could not tell which is authoritative.
    # Match a real level-3 heading only: a finding may quote one verbatim.
    generated = [heading for heading in GENERATED_SECTIONS if heading in heading_lines(report)]
    if generated:
        raise ValueError(
            f"{args.report} already contains {', '.join(generated)}, which persist appends; "
            "delete it from the report and let persist write it"
        )
    if coverage_section:
        report = report.rstrip() + "\n\n" + coverage_section
    if coverage_gap:
        # stderr alone is invisible in the persisted artifact: the report must say the map is
        # missing, or a reader of REVIEW.md sees a clean review of a partially read diff.
        print(f"warning: {coverage_gap}", file=sys.stderr)
        report = report.rstrip() + f"\n\n### Coverage\n- {coverage_gap}\n"
    if args.files:
        report = report.rstrip() + "\n\n### Files reviewed\n" + "".join(f"- `{name}`\n" for name in args.files)
    report = reviewed_at(args, report)
    if args.strict:
        # Per-finding rules always; the path-scoped evidence gate only when a path set exists. A spec
        # or idea review passes no paths, and gating the whole check on `--files` silently skipped
        # the `validation` requirement in exactly those modes.
        check_findings([f for f in findings if f.is_emitted()])
        if args.files:
            check_strict([f for f in findings if f.is_emitted()], args.files)
    rows = [f for f in findings if f.disposition == "defer"]
    args.review_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(args.review_dir / "REVIEW.md", report)
    task_report = "REVIEW.md" if args.mode in CODE_MODES else f"REVIEW.{args.mode}.md"
    atomic_write(owner / task_report, report)
    record_task_review(str(owner), args.review_dir)
    if rows:
        append_deferred(owner, rows)
    print(json.dumps({"review": str(owner / task_report), "deferred": len(rows)}))
    return 0


def outcome(args: argparse.Namespace) -> int:
    """Append one audit record for a finding's outcome to the review directory's journal."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "review_dir": str(args.review_dir),
        "fingerprint": args.fingerprint,
        "persona": canonical_personas(args.persona),
        "label": args.label,
        "outcome": args.outcome,
        "reason": args.reason,
        "memory_ids": args.memory_id,
    }
    target = args.review_dir.parent / "outcomes.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))
    return 0
