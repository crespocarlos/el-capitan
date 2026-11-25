#!/usr/bin/env python3
"""The `prior-review` subcommand: what an earlier round reviewed, and what it reported.

Two answers in one JSON object, because the orchestrator needs both before it builds packages: the
run directory to read the earlier findings from (`prior`), and the files whose current bytes match
what that round saw (`unchanged`). Writing the current run's manifest is a side effect, so a round
that forgets to record itself is detected by the next one rather than silently treated as new work.

A first review answers `prior: null` and an empty `unchanged`, and both are successes: only the
report of a directory that cannot be read is an error.
"""
from __future__ import annotations

import argparse
import json

import review_manifest as manifest


def prior_review(args: argparse.Namespace) -> int:
    """Write this run's manifest and print what the previous round covered."""
    review_dir = args.review_dir.resolve()
    previous = manifest.prior_review_dir(review_dir)
    current = manifest.manifest(args.repo.resolve(), args.paths)
    manifest.write(review_dir, current)
    unchanged = set()
    if previous is not None:
        earlier = manifest.read(previous)
        if earlier is not None:
            unchanged = manifest.unchanged_since(args.repo.resolve(), current, earlier)
    print(json.dumps({
        "prior": str(previous) if previous is not None else None,
        "unchanged": sorted(unchanged),
        "files": len(current["files"]),
    }, sort_keys=True))
    return 0
