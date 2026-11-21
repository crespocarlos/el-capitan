#!/usr/bin/env python3
"""Normalize review findings, persist review reports, and append outcome records.

Subcommands: `normalize`, `persist`, `select`, `coverage`, `validate-map`, `spec-context`,
`check-packages`, `outcome`. This file is the argparse entry point only: parsing, validation,
personas, layers, and report persistence live in the sibling `review_findings.py`,
`review_personas.py`, `review_layers.py`, and `review_report.py` modules. `Path(__file__).resolve()`
follows the installed `~/.agent/bin` symlink back to this directory, so the siblings and the `lib`
package above them are found from either invocation path.

The full contract — required finding fields, fingerprints, the strict gates, `--files` as an
evidence allowlist rather than a diff check, and `--head` tree identity — is documented in
`.agent/tools/TOOLS.md` under this command.
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
from review_report import outcome, persist  # noqa: E402,F401
from lib.output import DEFAULT_MAX_CHARS  # noqa: E402


def add_normalize_parsers(commands) -> None:
    """`normalize`, `persist`, and `select`: the candidate pipeline's write and dispatch steps."""
    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("input", type=Path)
    normalize_parser.add_argument("--output", type=Path)
    normalize_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                                  help="bound the printed JSON; --output is never truncated")
    normalize_parser.add_argument("--strict", action="store_true")
    normalize_parser.add_argument("--hunks", type=Path,
                                  help="hunks.json; with --strict, emitted findings must cite real hunk ids")
    normalize_parser.add_argument("--files", nargs="*", default=[],
                                  help="reviewed paths; strict evidence must point inside this set")
    persist_parser = commands.add_parser("persist")
    persist_parser.add_argument("--review-dir", required=True, type=Path)
    persist_parser.add_argument("--report", required=True, type=Path)
    persist_parser.add_argument("--findings", type=Path)
    persist_parser.add_argument("--mode", type=mode_arg,
                                choices=sorted(CODE_MODES | {"spec", "idea"}), default="self")
    persist_parser.add_argument("--files", nargs="*", default=[])
    persist_parser.add_argument("--strict", action="store_true")
    persist_parser.add_argument("--personas", nargs="*", default=[])
    persist_parser.add_argument("--head", default="", help="reviewed commit SHA recorded as `Reviewed at:`")
    select_parser = commands.add_parser("select")
    select_parser.add_argument("--mode", required=True, type=mode_arg,
                               choices=sorted(CODE_MODES | {"spec", "idea"}))
    select_parser.add_argument("--paths", nargs="*", default=[])
    select_parser.add_argument("--contract", action="store_true", help="a spec or PR contract supplies acceptance criteria")
    select_parser.add_argument("--compat", action="store_true", help="the change alters behavior of an existing consumer")
    select_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                               help="bound the printed JSON")


def add_map_parsers(commands) -> None:
    """`coverage` and `validate-map`: the layer map's two gates."""
    coverage_parser = commands.add_parser("coverage", help="fail on a hunk nobody was asked to read")
    coverage_parser.add_argument("--hunks", required=True, type=Path,
                                 help="hunks.json from crew-review-hunks.py")
    coverage_parser.add_argument("--layers", required=True, type=Path,
                                 help="layers.json written by the reviewer-layers pre-pass")
    coverage_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                                 help="bound the printed JSON")
    validate_parser = commands.add_parser("validate-map", help="check a whole review.json map")
    validate_parser.add_argument("--review", required=True, type=Path,
                                 help="review.json written by crew explain")
    validate_parser.add_argument("--hunks", required=True, type=Path,
                                 help="hunks.json the map was built from")
    validate_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                                 help="bound the printed JSON")


def add_context_parsers(commands) -> None:
    """`spec-context`, `check-packages`, and `outcome`: the per-persona and audit commands."""
    spec_parser = commands.add_parser("spec-context",
                                      help="print the part of SPEC.md one persona's package carries")
    spec_parser.add_argument("--persona", required=True)
    spec_parser.add_argument("spec", type=Path)
    packages_parser = commands.add_parser("check-packages",
                                          help="check written <persona>.in.md packages before dispatch")
    packages_parser.add_argument("--review-dir", required=True, type=Path)
    packages_parser.add_argument("--personas", nargs="+", required=True)
    packages_parser.add_argument("--mode", type=mode_arg,
                                 choices=sorted(CODE_MODES | {"spec", "idea"}), default="self")
    packages_parser.add_argument("--spec", type=Path, help="defaults to <task>/SPEC.md")
    outcome_parser = commands.add_parser("outcome")
    outcome_parser.add_argument("--review-dir", required=True, type=Path)
    outcome_parser.add_argument("--fingerprint", required=True)
    outcome_parser.add_argument("--persona", required=True)
    outcome_parser.add_argument("--label", required=True, choices=sorted(LABELS))
    outcome_parser.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    outcome_parser.add_argument("--reason", required=True)
    outcome_parser.add_argument("--memory-id", action="append", default=[])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize findings, persist reviews, select personas, and gate layer maps.")
    commands = parser.add_subparsers(dest="command", required=True)
    add_normalize_parsers(commands)
    add_map_parsers(commands)
    add_context_parsers(commands)
    args = parser.parse_args()
    handlers = {"normalize": normalize, "persist": persist, "select": select,
                "outcome": outcome, "coverage": coverage, "validate-map": validate_map,
                "spec-context": spec_context, "check-packages": check_packages}
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"review-findings: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
