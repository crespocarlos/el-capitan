#!/usr/bin/env python3
"""Report concerns: persist a review report and append outcome records.

Split out of `crew-review-findings.py`. `persist` writes the consolidated report to the review
directory and the task-level REVIEW file, appends deferred findings, and enforces the persona and
layer gates. Depends on `findings.py`, `personas.py`, and `layers.py`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from review_findings import (
    CODE_MODES,
    Finding,
    atomic_write,
    canonical_personas,
    check_findings,
    check_strict,
    read_findings,
    read_json_object,
)
from review_layers import check_coverage, check_hunk_refs, hunk_ids, layer_coverage
from review_personas import (
    GENERATED_SECTIONS,
    HUNKS_FILE,
    LAYERS_FILE,
    check_persona_coverage,
    package_violations,
)


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


def check_personas_present(args: argparse.Namespace) -> None:
    """Require a persona list and both artifacts for each, then prove each one produced output.

    Persona evidence is not a strict-only gate: a report persisted without proof that each
    dispatched persona ran is indistinguishable from a full review, so `--personas` is required
    on every call. `--strict` only adds the diff gates that need a clean tree to check.
    """
    if not args.personas:
        raise ValueError(
            "--personas is required: a persisted review must name the personas that produced it"
        )
    missing = [
        f"{persona}.{kind}.md"
        for persona in canonical_personas(args.personas, split_commas=False)
        for kind in ("in", "out")
        if not (args.review_dir / f"{persona}.{kind}.md").is_file()
    ]
    if missing:
        raise ValueError(f"missing persona artifacts in {args.review_dir}: {', '.join(missing)}")
    check_persona_coverage(args.review_dir, args.personas)


def strict_gates(args: argparse.Namespace, owner: Path, findings: list[dict]) -> tuple[str, str]:
    """Under `--strict`, enforce the layer, hunk, and package gates.

    Returns the coverage section to append and the coverage gap to report. A layer map is what
    proves the personas were pointed at the whole diff, so a hunk nobody was asked to read is a
    silent hole rather than a style point.
    """
    layers_path = args.review_dir / LAYERS_FILE
    hunks_path = args.review_dir / HUNKS_FILE
    coverage_section = coverage_gap = ""
    if layers_path.is_file():
        if not hunks_path.is_file():
            raise ValueError(
                f"{layers_path} has no sibling {HUNKS_FILE}; a layer map without a hunk index cannot be checked"
            )
        check_coverage(hunks_path, layers_path)
        coverage_section = layer_coverage(read_json_object(layers_path, "layers")["layers"], findings)
    elif hunks_path.is_file():
        coverage_gap = (
            f"{HUNKS_FILE} has no {LAYERS_FILE}: hunk coverage was not enforced, so no layer of "
            "this diff is proven to have been read"
        )
    if hunks_path.is_file():
        check_hunk_refs(findings, hunk_ids(hunks_path))
    # Directories written before package.diff existed hold diff.patch and the full spec, so the
    # package rules only apply to a review that was packaged under them.
    if (args.review_dir / "package.diff").is_file():
        violations, _ = package_violations(args.review_dir, args.personas, args.mode,
                                           owner / "SPEC.md", hunks_path)
        if violations:
            raise ValueError("; ".join(violations))
    return coverage_section, coverage_gap


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
        exists = subprocess.run(["git", "cat-file", "-e", f"{head}^{{commit}}"],
                                capture_output=True)
        if exists.returncode:
            raise ValueError(f"--head {head} is not a commit in this repository")
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
    if rows:
        append_deferred(owner, rows)
    print(json.dumps({"review": str(owner / task_report), "deferred": len(rows)}))
    return 0


def outcome(args: argparse.Namespace) -> int:
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
