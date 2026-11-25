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
    strict_mode,
)
from review_persist_gates import check_assessments, check_personas_present, strict_gates
from review_render import footer
from review_report_gate import check_report
from review_report_sections import GENERATED_SECTIONS, assessment_section, heading_lines
from review_workspace import record_task_review
import review_comments as comments
import review_outcomes as outcomes
import review_records as records


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


def reviewed_head(args: argparse.Namespace) -> str:
    """The reviewed commit after checking the SHA is real, or "" when none was passed.

    `crew commit` moves HEAD past the reviewed tree, so the gate downstream accepts an ancestor;
    recording the SHA still makes a review of a *different* tree detectable. PR mode is the
    exception: the reviewed tree is the GitHub head and the local checkout never fetches it, so a
    local existence check would reject every PR review. Only the validated value comes back: the
    footer is the one place a report states it, so a second append site cannot disagree.
    """
    if not args.head:
        return ""
    head = args.head.strip()
    if not re.fullmatch(r"[0-9a-f]{7,40}", head):
        raise ValueError(f"--head must be a commit SHA, got {head!r}")
    if args.mode != "pr":
        try:
            rev_parse(None, f"{head}^{{commit}}")
        except GitError:
            raise ValueError(f"--head {head} is not a commit in this repository") from None
    return head


def append_deferred(owner: Path, rows: list[Finding]) -> dict[str, int]:
    """Record the deferred and dropped findings beside the report; see `review_records`."""
    return records.append(owner, rows)


def assemble_report(args: argparse.Namespace, report: str, coverage_section: str,
                    coverage_gap: str, findings: list[Finding], head: str,
                    assessments_section: str = "") -> str:
    """The report body with its generated sections and the decision footer, appended in order.

    Every generated section arrives as a parameter, computed by `persist`, so this function's
    signature names its inputs and reads as "the body plus everything derived from it". `Reviewed
    at:` is skipped when `--head` was empty, but a local review still gets its next step. Hanging the
    footer off the commit instead would leave exactly those reviews with no next step a reader could
    find.

    The derived `Verdict:` line is written only when findings were supplied. With no `--findings`
    there is no comparison, and a verdict derived from an empty list would be `PASS` on a report whose
    own body may say `BLOCK` — a second, unchecked claim stamped on the one path the gate cannot see.
    """
    # The generated sections are derived from --findings, --files, and the persona replies, so a
    # report carrying its own copy would render the table twice and a reader could not tell which is
    # authoritative. Match a real level-3 heading only: a finding may quote one verbatim.
    generated = [heading for heading in GENERATED_SECTIONS if heading in heading_lines(report)]
    if generated:
        raise ValueError(
            f"{args.report} already contains {', '.join(generated)}, which persist appends; "
            "delete it from the report and let persist write it"
        )
    if assessments_section:
        report = report.rstrip() + "\n\n" + assessments_section
    if coverage_section:
        report = report.rstrip() + "\n\n" + coverage_section
    if coverage_gap:
        # stderr alone is invisible in the persisted artifact: the report must say the map is
        # missing, or a reader of REVIEW.md sees a clean review of a partially read diff.
        print(f"warning: {coverage_gap}", file=sys.stderr)
        report = report.rstrip() + f"\n\n### Coverage\n- {coverage_gap}\n"
    if args.files:
        report = report.rstrip() + "\n\n### Files reviewed\n" + "".join(
            f"- `{name}`\n" for name in args.files)
    step = footer(findings, head, args.mode, args.next,
                  derived=bool(args.findings))
    return report.rstrip() + "\n\n" + step + "\n"



def persist(args: argparse.Namespace) -> int:
    """Write the report, the coverage section, and the deferred findings, after every gate."""
    owner = validate_review_dir(args)
    findings = read_findings(args.findings) if args.findings else []
    check_personas_present(args)
    assessments_section = assessment_section(check_assessments(args.review_dir, args.personas))
    head = reviewed_head(args)
    body = args.report.read_text(encoding="utf-8")
    coverage_section = coverage_gap = ""
    strict = strict_mode(args)
    if strict:
        coverage_section, coverage_gap = strict_gates(args, owner, findings)
    report = assemble_report(args, body, coverage_section, coverage_gap, findings, head,
                             assessments_section)
    if strict:
        # Per-finding rules always; the path-scoped evidence gate only when a path set exists. A spec
        # or idea review passes no paths, and gating the whole check on `--files` silently skipped
        # the `validation` requirement in exactly those modes.
        check_findings([f for f in findings if f.is_emitted()])
        if args.files:
            check_strict([f for f in findings if f.is_emitted()], args.files)
    if args.findings:
        # The body, not the assembled report: the footer states the derived verdict, so comparing it
        # would let any contradiction in the model's own list pass its own gate.
        check_report(body, findings, args.mode)
    rows = [f for f in findings if f.disposition in records.RECORDED_DISPOSITIONS]
    args.review_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(args.review_dir / "REVIEW.md", report)
    task_report = "REVIEW.md" if args.mode in CODE_MODES else f"REVIEW.{args.mode}.md"
    atomic_write(owner / task_report, report)
    record_task_review(str(owner), args.review_dir)
    counts = append_deferred(owner, rows) if rows else {}
    written = [str(owner / task_report)]
    drafted = comments.write_for_mode(args.review_dir, findings, args.mode, args.head)
    if drafted:
        written.append(str(drafted))
    # A PR review's `comments.md` is its deliverable. Reporting it as absent in the JSON — rather than
    # only on stderr — is what stops Step 8 from describing a review whose findings never reach the PR.
    missing_comments = args.mode == "pr" and not drafted
    print(json.dumps({"review": written[0],
                      "deferred": sum(1 for f in rows if f.disposition == "defer"),
                      "dropped": sum(1 for f in rows if f.disposition == "dropped"),
                      "appended": counts.get("DEFERRED.md", 0) + counts.get("DROPPED.md", 0),
                      **({"comments": written[1]} if len(written) > 1 else {}),
                      **({"comments_missing": True} if missing_comments else {})}))
    return 0


def check_outcomes(args: argparse.Namespace) -> int:
    """Report what a review recorded, and fail when an acted finding has no outcome.

    Exit 1, not 2: the command ran and found a gap in the run's own bookkeeping, which is a
    finding rather than an unusable invocation. A summary that claimed success while a decision it
    made went unrecorded is exactly the drift this exists to make visible.
    """
    review_dir = args.review_dir.resolve()
    recorded = outcomes.summary(review_dir)
    missing = outcomes.missing(review_dir, args.acted)
    payload = {**recorded, "acted": len(args.acted), "missing": missing}
    print(json.dumps(payload, sort_keys=True))
    return 1 if missing else 0


def outcome(args: argparse.Namespace) -> int:
    """Append one audit record for a finding's outcome, carrying the score it was decided under."""
    return outcomes.append(args)
