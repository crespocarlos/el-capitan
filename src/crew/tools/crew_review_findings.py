#!/usr/bin/env python3
"""Normalize review findings, persist review reports, and append outcome records.

Subcommands: `normalize`, `persist`, `select`, `coverage`, `spec-context`, `check-packages`, `outcomes`,
`review-dir`, `save-out`, `expect`, `capture`, `dispatch-bytes`, `cache-report`. A review's setup, dispatch,
consolidation and an outcome are the agent verbs `crew-tool.py review-*`. Entry point only: logic in the `review_*` modules.
Contract (fields, fingerprints, evidence gates, `--files`, `--head`): `src/crew/TOOLS.md`.
"""

from __future__ import annotations

import argparse
import json
import sys

from crew.core.review.review_capture import add_capture_parsers, capture, expect, save_out_command

# Re-exported deliberately: `assemble-packages.py` imports PERSONAS from this file as the single
# persona registry, and the contract tests import the classifier and the label pattern to exercise
# them directly. A caller must not have to know which private module now owns them.
from crew.core.review.review_cli import add_context_parsers, add_map_parsers, add_map_reply_parser, add_mode_flags, add_normalize_parsers, add_review_dir_parser
from crew.core.review.review_coverage import check_packages, check_persona_coverage, package_violations, select, spec_context, spec_for, spec_sections
from crew.core.review.review_dispatch_stats import add_stats_parsers, cache_report, dispatch_bytes
from crew.core.review.review_findings import check_findings, normalize, read_findings
from crew.core.review.review_layers import check_coverage, check_hunk_refs, coverage, hunk_ids, layer_coverage
from crew.core.review.review_models import fingerprint
from crew.core.review.review_pr_plan import check_map, comments
from crew.core.review.review_render import add_save_out_parser
from crew.core.review.review_report import check_outcomes, persist
from crew.core.review.review_vocabulary import (
    CODE_MODES,
    EMITTED,
    KINDS,
    LABELED_FINDING,
    LABELS,
    OUTCOMES,
    PERSONAS,
    canonical_personas,
    mode_arg,
    persona_outcome,
)
from crew.core.review.review_workspace import claim, cleanup_stale, prior_review, report, review_dir
from crew.lib.files import atomic_write
from crew.lib.output import DEFAULT_MAX_CHARS

__all__ = [  # the public names: re-exported for callers and tests that import this command file
    "add_mode_flags",
    "atomic_write",
    "canonical_personas",
    "check_coverage",
    "check_findings",
    "check_hunk_refs",
    "check_persona_coverage",
    "CODE_MODES",
    "DEFAULT_MAX_CHARS",
    "EMITTED",
    "fingerprint",
    "hunk_ids",
    "KINDS",
    "LABELED_FINDING",
    "LABELS",
    "layer_coverage",
    "main",
    "mode_arg",
    "OUTCOMES",
    "package_violations",
    "persona_outcome",
    "PERSONAS",
    "read_findings",
    "spec_for",
    "spec_sections",
]


def review_dir_command(args: argparse.Namespace) -> int:
    """Create the review directory and print it; `--prune` also trims old temp dirs."""
    chosen = review_dir(args.task_dir or None, args.repo or None, args.mode)
    claim(chosen, args.mode, args.repo or None, args.task_dir or None)
    if args.prune:
        cleanup_stale(chosen.parent, chosen)
    return report(chosen, args.task_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize findings, persist reviews, select personas, and gate layer maps.")
    commands = parser.add_subparsers(dest="command", required=True)
    add_normalize_parsers(commands)
    add_map_parsers(commands)
    add_map_reply_parser(commands)
    add_context_parsers(commands)
    add_review_dir_parser(commands)
    add_save_out_parser(commands)
    add_capture_parsers(commands)
    add_stats_parsers(commands)
    args = parser.parse_args(argv)
    handlers = {
        "normalize": normalize,
        "persist": persist,
        "select": select,
        "outcomes": check_outcomes,
        "coverage": coverage,
        "spec-context": spec_context,
        "check-packages": check_packages,
        "review-dir": review_dir_command,
        "prior-review": prior_review,
        "save-out": save_out_command,
        "expect": expect,
        "capture": capture,
        "dispatch-bytes": dispatch_bytes,
        "cache-report": cache_report,
        "comments": comments,
        "check-map": check_map,
    }
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"review-findings: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
