#!/usr/bin/env python3
"""Compose one reviewer context package per persona from a review run's artifacts.

Usage: assemble-packages.py <review-dir> [--config <file>]

A package is deterministic text built from files the run already produced:

    shared header   the shared reviewer contract, the mode block, the hunk reference with its
                    citation rule, and repo memory
    diff            `package.diff` (generated files already collapsed by `review-hunks.py`)
    per persona     the size gate, the per-persona spec (`spec.<persona>.md`, written by
                    `review-findings.py spec-context`), the reading map derived from
                    `layers.json`, repository guidance narrowed to the sections that lens uses,
                    the prior-round block, consumer excerpts for the code lenses, and complete
                    prompt files for Prompt Quality

Every persona's package contains the same contract, mode block, hunk reference, memory and diff,
built by this tool in one fixed order. Hand-assembling five of them is how an earlier run gave one
reviewer a different header and another a prebuilt `_common.md` instead of the contract: the
packages still passed `check-packages`, because that gate checks the rules whose absence is
detectable, not whether two reviewers read the same evidence.

The shared material and the whole diff come first because they are byte-identical across the five
packages, so a harness that caches a prompt prefix pays for them once per run instead of once per
persona; the material that differs by lens follows the diff. Guidance is the one per-run section
narrowed per lens, so it sits with the per-persona material and every dropped heading is printed.

Per-run judgement stays in a config file, not in code: the review directory may carry
`assemble.json` with

    {"repo": "<repository root>", "mode": "<markdown block>", "size_gate": "<one-line summary>",
     "consumers": [[path, start, end, label], ...], "prompt_files": [path, ...],
     "guidance_keep": {"<persona>": ["<level-2 heading prefix>", ...]}, "mode_kind": "pr"}

`--config` names a different file. Missing keys mean "no such section". The mode block falls back to
the label vocabulary and return shape only, because a package with no mode leaves a persona without
its legal labels; the fallback deliberately says nothing about which tree to read, since that differs
by mode. `mode_kind: "pr"` refuses `consumers` and `prompt_files`: both read the local git index,
which a PR review forbids.

This file is the argparse entry point only: the config, the shared header, the reading map, the
prompt tier, and the build live in the `assemble_*.py` siblings beside it.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_REVIEW_DIR = pathlib.Path(__file__).resolve().parent
_TOOLS_ROOT = _REVIEW_DIR.parent
for _path in (_TOOLS_ROOT, _REVIEW_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from assemble_build import assemble_all, build, write_packages  # noqa: E402,F401
from assemble_common import HUNK_SENTENCE, common  # noqa: E402,F401
from assemble_config import (  # noqa: E402,F401
    DEFAULT_MODE,
    check_inputs,
    contract_path,
    keep_sections,
    narrow_guidance,
    read_config,
    read_json,
)
from assemble_files import covered_lines, excerpt, full_file, is_staged, staged_text  # noqa: E402,F401
from assemble_map import CONSUMER_LENSES, PRIMARY_KINDS, reading_map  # noqa: E402,F401
from assemble_personas import CANONICAL, PERSONAS, reviewer_personas  # noqa: E402,F401


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compose one reviewer context package per persona from a review run's artifacts.",
        epilog="Per-run judgement comes from assemble.json in the review directory; see the module "
               "docstring for every key.",
    )
    parser.add_argument("review_dir", type=pathlib.Path, help="<task>/review/<timestamp>")
    parser.add_argument("--config", type=pathlib.Path,
                        help="config file, default <review_dir>/assemble.json")
    args = parser.parse_args(argv)
    review_dir = args.review_dir.resolve()
    config = read_config(review_dir, args.config.resolve() if args.config else None)
    problem = check_inputs(review_dir, config)
    if problem:
        print(f"assemble-packages: {problem}", file=sys.stderr)
        return 2
    hunks_path = review_dir / "hunks.json"
    hunks_json = read_json(hunks_path, "the hunk index") if hunks_path.is_file() else None
    try:
        assembled = assemble_all(review_dir, config, hunks_json)
    except ValueError as error:
        print(f"assemble-packages: {error}", file=sys.stderr)
        return 2
    write_packages(review_dir, assembled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
