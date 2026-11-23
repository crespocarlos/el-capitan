#!/usr/bin/env python3
"""The subcommand definitions for `crew-review-findings.py`, kept out of the entry point.

The entry point holds argparse wiring and exit codes only, and the module ceiling is 200 lines; the
flags for eleven subcommands are more than that budget allows once the handlers are counted. Every
argument shape a prompt uses is defined here so the help text and the parser cannot disagree.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from lib.output import DEFAULT_MAX_CHARS
from review_findings import CODE_MODES, LABELS, OUTCOMES, mode_arg


def add_mode_flags(parser: argparse.ArgumentParser) -> None:
    """The default-on evidence gates, with both the escape and the legacy spelling accepted.

    `--strict` stays a no-op alias for one cycle so a script or prompt written against the old
    default keeps working; `--lenient` is the documented way to skip the gates. `--strict` is
    suppressed from `--help` because it is not the way to opt in any more.
    """
    parser.add_argument("--lenient", action="store_true",
                        help="skip the evidence gates; the checked behaviour is the default")
    parser.add_argument("--strict", action="store_true", help=argparse.SUPPRESS)


def add_review_dir_parser(commands) -> None:
    """`review-dir`: create and print the directory this review writes into."""
    parser = commands.add_parser(
        "review-dir", help="create and print the directory this review writes into")
    parser.add_argument("--task-dir", default="",
                        help="the resolved task directory, empty when there is none")
    parser.add_argument("--mode", default="self", help="pr always uses a temp directory")
    parser.add_argument("--repo", default="", help="named in the temp path")
    parser.add_argument("--prune", action="store_true",
                        help="remove temp review directories beyond the newest ten")


def add_normalize_parsers(commands) -> None:
    """`normalize`, `persist`, and `select`: the candidate pipeline's write and dispatch steps."""
    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("input", type=Path)
    normalize_parser.add_argument("--output", type=Path)
    normalize_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                                  help="bound the printed JSON; --output is never truncated")
    add_mode_flags(normalize_parser)
    normalize_parser.add_argument("--hunks", type=Path,
                                  help="hunks.json; emitted findings must cite real hunk ids")
    normalize_parser.add_argument("--files", nargs="*", default=[],
                                  help="reviewed paths; evidence must point inside this set")
    persist_parser = commands.add_parser("persist")
    persist_parser.add_argument("--review-dir", required=True, type=Path)
    persist_parser.add_argument("--report", required=True, type=Path)
    persist_parser.add_argument("--findings", type=Path)
    persist_parser.add_argument("--mode", type=mode_arg,
                                choices=sorted(CODE_MODES | {"spec", "idea"}), default="self")
    persist_parser.add_argument("--files", nargs="*", default=[])
    add_mode_flags(persist_parser)
    persist_parser.add_argument("--personas", nargs="*", default=[])
    persist_parser.add_argument("--head", default="",
                                help="reviewed commit SHA recorded as `Reviewed at:`")
    select_parser = commands.add_parser("select")
    select_parser.add_argument("--mode", required=True, type=mode_arg,
                               choices=sorted(CODE_MODES | {"spec", "idea"}))
    select_parser.add_argument("--paths", nargs="*", default=[])
    select_parser.add_argument("--contract", action="store_true",
                               help="a spec or PR contract supplies acceptance criteria")
    select_parser.add_argument("--compat", action="store_true",
                               help="the change alters behavior of an existing consumer")
    select_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                               help="bound the printed JSON")


def add_map_parsers(commands) -> None:
    """`coverage` and `validate-map`: the layer map's two gates."""
    coverage_parser = commands.add_parser(
        "coverage", help="fail on a hunk nobody was asked to read")
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
    """`spec-context`, `check-packages`, `comments`, and the two outcome subcommands."""
    spec_parser = commands.add_parser(
        "spec-context", help="print the part of SPEC.md one persona's package carries")
    spec_parser.add_argument("--persona", required=True)
    spec_parser.add_argument("spec", type=Path)
    packages_parser = commands.add_parser(
        "check-packages", help="check written <persona>.in.md packages before dispatch")
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
    outcome_parser.add_argument("--confidence", type=int, default=None,
                                help="the score this decision was made under, after any raise")
    outcome_parser.add_argument("--confidence-from", type=int, default=None,
                                help="the score it arrived with, when this decision raised it")
    outcome_parser.add_argument("--validation", default=None,
                                help="the read that settled a raise; required when the score rises")
    check_parser = commands.add_parser(
        "outcomes", help="report a review's recorded outcomes; --acted fails on a missing one")
    check_parser.add_argument("--review-dir", required=True, type=Path)
    check_parser.add_argument("--acted", nargs="*", default=[],
                              help="fingerprints this run applied or rejected; each needs one")
    comments_parser = commands.add_parser(
        "comments", help="write comments.md, one paste-ready body per anchored finding")
    comments_parser.add_argument("--review-dir", required=True, type=Path)
    comments_parser.add_argument("--findings", type=Path,
                                 help="consolidation.json; defaults to the one in --review-dir")
    comments_parser.add_argument("--head", default="",
                                 help="the reviewed SHA, recorded in the draft")
    comments_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                                 help="bound the printed summary")


def add_map_reply_parser(commands) -> None:
    """`check-map`: parse a reviewer-layers reply before it is written as `layers.json`."""
    parser = commands.add_parser(
        "check-map", help="parse a reviewer-layers reply and optionally write layers.json")
    parser.add_argument("reply", type=Path, help="the file holding the reply text")
    parser.add_argument("--output", type=Path, help="write the parsed map here")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help="bound the printed summary")
