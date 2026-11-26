#!/usr/bin/env python3
"""A degraded review: fewer agents than lenses, so the lenses were not independent.

A fork cannot dispatch subagents, so one agent sometimes plays every lens. That review is useful and
must say what it is: its output starts with `Degraded: 1 agent, N lenses`, `report.md` carries the
same line, and its verdict is capped at `WARN` (a `PASS` becomes `WARN`, a `BLOCK` stays `BLOCK`).
`review_vocabulary.verdict` is untouched and keeps its three labels; only the report of a degraded
run goes through `capped`, so every consumer of the verdict still reads `BLOCK | WARN | PASS`.
"""
from __future__ import annotations

CAP_NOTE = "The lenses were not independent agents, so the verdict is capped at WARN."


def capped(verdict: str, degraded: bool) -> str:
    """`WARN` for a degraded `PASS`; every other verdict, and every non-degraded one, unchanged."""
    return "WARN" if degraded and verdict == "PASS" else verdict


def banner(agents: int, lenses: int) -> str:
    """The first line of a degraded review."""
    return f"Degraded: {agents} agent{'' if agents == 1 else 's'}, {lenses} lenses"


def with_banner(body: str, line: str) -> str:
    """`body` opened by the banner and the cap note; a body that already starts with one is kept."""
    return body if body.startswith("Degraded:") else f"{line}\n{CAP_NOTE}\n\n{body}"
