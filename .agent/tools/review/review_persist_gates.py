#!/usr/bin/env python3
"""The gates a persisted review must pass before it is written.

Persona evidence is not a strict-only gate: a report persisted without proof that each dispatched
persona ran is indistinguishable from a full review, so the persona check runs on every call.
`--strict` adds the diff gates that need a clean tree to check — the layer map, the hunk references,
and the package rules — and a layer map without its hunk index is an error rather than a silent
hole, because a hunk nobody was asked to read is exactly the failure this guards.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from review_findings import canonical_personas, read_json_object
from review_layers import check_coverage, check_hunk_refs, hunk_ids, layer_coverage
from review_personas import HUNKS_FILE, LAYERS_FILE, check_persona_coverage, package_violations


def check_personas_present(args: argparse.Namespace) -> None:
    """Require a persona list and both artifacts for each, then prove each one produced output."""
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
