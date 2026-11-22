#!/usr/bin/env python3
"""Normalize review findings, persist review reports, and append outcome records.

Subcommands: `normalize`, `persist`, `select`, `coverage`, `validate-map`, `spec-context`,
`check-packages`, `outcome`, `outcomes`, `review-dir`. This file is the argparse entry point only:
parsing and validation live in the sibling `review_findings.py`, the flag definitions in
`review_cli.py`, personas in `review_personas.py`, layers in `review_layers.py`, and report
persistence in `review_report.py`. `Path(__file__).resolve()` follows the installed `~/.agent/bin`
symlink back to this directory, so the siblings and the `lib` package above them are found from
either invocation path.

The full contract — required finding fields, fingerprints, the evidence gates and `--lenient`,
`--files` as an evidence allowlist rather than a diff check, and `--head` tree identity — is
documented in `.agent/tools/TOOLS.md` under this command.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REVIEW_DIR = Path(__file__).resolve().parent
_TOOLS_ROOT = _REVIEW_DIR.parent
for _path in (_TOOLS_ROOT, _REVIEW_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# Re-exported deliberately: `assemble-packages.py` imports PERSONAS from this file as the single
# persona registry, and the contract tests import the classifier and the label pattern to exercise
# them directly. A caller must not have to know which private module now owns them.
from review_findings import (  # noqa: E402,F401
    CODE_MODES,
    EMITTED,
    KINDS,
    LABELS,
    LEGACY_PERSONAS,
    MAX_FINDINGS,
    MAX_NITS,
    OUTCOMES,
    PERSONAS,
    atomic_write,
    canonical_personas,
    check_findings,
    check_strict,
    fingerprint,
    mode_arg,
    normalize,
    normalized_title,
    read_findings,
    strict_mode,
)
from review_layers import (  # noqa: E402,F401
    check_coverage,
    check_hunk_refs,
    check_layers,
    coverage,
    hunk_ids,
    layer_coverage,
    validate_map,
)
from review_personas import (  # noqa: E402,F401
    ANCHOR_ANYWHERE,
    EXPLORER_FINDING,
    FIX_RESPONSE_FINDING,
    LABELED_FINDING,
    LABEL_LINE,
    QUOTED_EVIDENCE,
    SPEC_FINDING,
    SUMMARY_ARTIFACT,
    VERDICT_NO_FINDINGS,
    check_packages,
    check_persona_coverage,
    has_findings,
    has_review_content,
    package_violations,
    persona_outcome,
    select,
    spec_context,
    spec_for,
    spec_sections,
)
from review_report import check_outcomes, outcome, persist  # noqa: E402,F401
from lib.output import DEFAULT_MAX_CHARS  # noqa: E402


from review_workspace import claim, cleanup_stale, report, review_dir  # noqa: E402
from review_cli import (  # noqa: E402,F401
    add_context_parsers,
    add_map_parsers,
    add_mode_flags,
    add_normalize_parsers,
    add_review_dir_parser,
)


def review_dir_command(args: argparse.Namespace) -> int:
    """Create the review directory and print it; `--prune` also trims old temp dirs."""
    chosen = review_dir(args.task_dir or None, args.repo or None, args.mode)
    claim(chosen, args.mode, args.repo or None, args.task_dir or None)
    if args.prune:
        cleanup_stale(chosen.parent, chosen)
    return report(chosen, args.task_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize findings, persist reviews, select personas, and gate layer maps.")
    commands = parser.add_subparsers(dest="command", required=True)
    add_normalize_parsers(commands)
    add_map_parsers(commands)
    add_context_parsers(commands)
    add_review_dir_parser(commands)
    args = parser.parse_args()
    handlers = {"normalize": normalize, "persist": persist, "select": select,
                "outcome": outcome, "outcomes": check_outcomes, "coverage": coverage,
                "validate-map": validate_map, "spec-context": spec_context,
                "check-packages": check_packages, "review-dir": review_dir_command}
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"review-findings: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
