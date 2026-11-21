#!/usr/bin/env python3
"""The persona registry, read from `crew-review-findings.py` so there is one registry, not two.

`explorer` is dispatched by hand after the personas and never gets a lens package, so it is the one
name in that set this tool must not package. Adding a persona then touches `crew-review-findings.py`
and the files `AGENTS.md`'s checklist names, not a fourth hard-coded tuple here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

CANONICAL = ("adversarial", "architecture", "code-quality", "product-flow", "prompt-quality")


def reviewer_personas() -> tuple[str, ...]:
    """The reviewer names that receive a package, in the canonical order."""
    tool = Path(__file__).with_name("crew-review-findings.py")
    spec = importlib.util.spec_from_file_location("review_findings_for_personas", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    known = {name for name in module.PERSONAS if name != "explorer"}
    missing = known - set(CANONICAL)
    if missing:
        raise SystemExit(
            f"assemble-packages: {', '.join(sorted(missing))} is a reviewer persona with no entry "
            "here; add it with its primary layer kinds in PRIMARY_KINDS"
        )
    return tuple(name for name in CANONICAL if name in known)


PERSONAS = reviewer_personas()
