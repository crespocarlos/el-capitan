#!/usr/bin/env python3
"""Persona concerns: output classification, selection, coverage, packages, and spec context.

Split out of `crew-review-findings.py`. Everything here answers a question about reviewers rather
than about findings: which lenses to dispatch, whether each one actually produced output, and
what a persona package must contain. The classifier is `review_classify` and the package rules are
`review_coverage`; this module re-exports both and holds the three subcommands that report on them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.output import bounded_json
from review_classify import (  # noqa: F401 — re-exported
    ANCHOR_ANYWHERE,
    EXPLORER_FINDING,
    EXPLORER_SECTIONS,
    FIX_RESPONSE_FINDING,
    LABELED_FINDING,
    LABEL_LINE,
    NO_FINDINGS,
    QUOTED_EVIDENCE,
    SPEC_FINDING,
    SUMMARY_ARTIFACT,
    has_findings,
    has_review_content,
    persona_outcome,
)
from review_coverage import (  # noqa: F401 — re-exported
    GENERATED_SECTIONS,
    HUNKS_FILE,
    LAYERS_FILE,
    check_persona_coverage,
    package_violations,
    spec_for,
    spec_sections,
)
from review_vocabulary import CODE_MODES, SELECT_RULES, canonical_personas


def select(args: argparse.Namespace) -> int:
    """The lenses a change requires, each with the reason it was selected."""
    required = {}
    if args.mode in CODE_MODES:
        required["code-quality"] = "code review"
        required["adversarial"] = "code review"
        for persona, pattern in SELECT_RULES.items():
            hits = [path for path in args.paths if pattern.search(path)]
            if hits:
                required[persona] = f"paths: {', '.join(hits[:3])}"
        if args.compat:
            required.setdefault("architecture", "--compat")
    else:
        # Specs and ideas have no diff to review, so the lenses are fixed rather than
        # derived from paths; otherwise the selection is empty and nothing is dispatched.
        required["product-flow"] = "plan coherence"
        required["adversarial"] = "plan failure modes"
        required.setdefault("architecture", "plan boundaries and compatibility")
    if args.contract:
        required["product-flow"] = "--contract"
    payload = {"required": sorted(required), "reasons": required}
    print(bounded_json(payload, args.max_chars, what="selected personas"))
    return 0


def spec_context(args: argparse.Namespace) -> int:
    """Print the part of SPEC.md one persona's package carries."""
    persona = canonical_personas([args.persona], split_commas=False)[0]
    sys.stdout.write(spec_for(persona, args.spec.read_text(encoding="utf-8")))
    return 0


def check_packages(args: argparse.Namespace) -> int:
    """Check written `<persona>.in.md` packages before dispatch."""
    review_dir = args.review_dir.resolve()
    if review_dir.parent.name != "review" and not args.spec:
        raise ValueError(
            f"--review-dir must be <task>/review/<timestamp> (got {review_dir}); "
            "pass --spec when the directory is laid out differently"
        )
    spec = args.spec or review_dir.parent.parent / "SPEC.md"
    violations, report = package_violations(review_dir, args.personas, args.mode, spec,
                                            review_dir / HUNKS_FILE)
    if not report["read"]:
        violations.append(f"no <persona>.in.md found in {review_dir} for {', '.join(args.personas)}")
    for violation in violations:
        print(f"review-findings: {violation}", file=sys.stderr)
    if not violations:
        print(json.dumps({"ok": True, "packages": len(report["read"]), "skipped": report["skipped"]}))
    return 1 if violations else 0
