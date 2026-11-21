#!/usr/bin/env python3
"""The `doctor` preflight: the checks in the order that matters, and their JSON report.

Checks are ordered by what actually blocks a run, and the blocking set stops at the first stage
that cannot answer: with no checkout there is nothing to ask, and with no server the config probe
would only produce a second failure for the first one's cause. `ok` is the verdict over the
blocking checks only; the notes are reported beside it and never change it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nightshift.checks import (
    config_checks,
    location_checks,
    machine_notes,
    server_checks,
)
from nightshift.client import base_url
from nightshift.location import elastic_remote, resolve_root


def report_doctor(root: Path, checks: list[dict], notes: list[dict]) -> int:
    """Print the report; 0 when every blocking check passed, 1 otherwise."""
    ok = all(entry["ok"] for entry in checks)
    print(json.dumps({"root": str(root), "url": base_url(), "ok": ok,
                      "checks": checks, "notes": notes}, indent=2))
    return 0 if ok else 1


def doctor(_args: argparse.Namespace) -> int:
    """Preflight for `crew e2e`, with checks ordered by what actually blocks a run.

    Nothing in `checks` is a warning: `crew e2e` starts real e2e runs, so a check that cannot pass
    must stop the skill. `launchd` and `build_fresh` are notes, and deliberately so: a server
    started with `npm run dev` answers and works, so gating on a LaunchAgent would reject a
    perfectly usable machine.
    """
    root, source = resolve_root()
    checks = location_checks(root, source)
    if not root.is_dir():
        return report_doctor(root, checks, [])
    remote, _ = elastic_remote(root)
    notes = machine_notes(root, remote)
    server, queue = server_checks(root)
    checks.extend(server)
    if queue is None:
        return report_doctor(root, checks, notes)
    config, config_notes = config_checks(root)
    checks.extend(config)
    notes.extend(config_notes)
    return report_doctor(root, checks, notes)
