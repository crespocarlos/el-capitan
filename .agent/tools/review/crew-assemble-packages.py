#!/usr/bin/env python3
"""Compose one reviewer context package per persona from a review run's artifacts.

Usage: crew-assemble-packages.py <review-dir>. Each package is the shared head
(contract, mode, hunk reference, memory), the whole `package.diff`, then the per-persona tail, so
every reviewer reads the same evidence and a cached prefix is paid once. Per-run judgement comes
from `assemble.json` (keys and rules: `.agent/tools/TOOLS.md`); inputs `assemble_inputs`, build `assemble_build`.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import review_bootstrap  # noqa: F401

from assemble_build import assemble_run, write_run
from assemble_inputs import check_inputs, read_artifact, read_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compose one reviewer context package per persona from a review run's artifacts.",
        epilog="Per-run judgement comes from assemble.json in the review directory; see the module "
               "docstring for every key.",
    )
    parser.add_argument("review_dir", type=pathlib.Path, help="<task>/review/<timestamp>")
    args = parser.parse_args(argv)
    review_dir = args.review_dir.resolve()
    config = read_config(review_dir)
    problem = check_inputs(review_dir, config)
    if problem:
        print(f"assemble-packages: {problem}", file=sys.stderr)
        return 2
    hunks_path = review_dir / "hunks.json"
    hunks_json = read_artifact(hunks_path, "the hunk index") if hunks_path.is_file() else None
    try:
        run = assemble_run(review_dir, config, hunks_json)
    except ValueError as error:
        print(f"assemble-packages: {error}", file=sys.stderr)
        return 2
    write_run(review_dir, *run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
