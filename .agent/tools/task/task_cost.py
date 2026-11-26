"""The stage cost line: what a `crew implement` or `crew review` run cost, as its harness reported it.

Tokens exist only in the harness, never in the tools, so the orchestrator passes what it was told:
`crew-metric.py <TASK_DIR> stage_end stage=implement workers=3 tokens_reported=410000`. The writer
validates the keys and prints the one line the stage ends with ("implement: 3 workers, 410k tokens");
`crew ls --cost` reads the same METRIC lines back. `tokens_reported=unknown` is a value, not an error:
a harness that gives nothing says so and the number is never guessed.

    stage_start stage=<implement|review>
    stage_end   stage=<implement|review> [workers=<n>] [personas=<n>] tokens_reported=<n|unknown>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

STAGES = {"implement": "workers", "review": "personas"}
KEYS = ("stage_start", "stage_end")
METRIC = re.compile(r"METRIC:\s+(stage_start|stage_end)\b(.*)$")


def fields(words: list[str]) -> dict[str, str]:
    return {k: v for k, _, v in (word.partition("=") for word in words if "=" in word)}


def validate(words: list[str]) -> str | None:
    """The problem with a metric payload, or None. Only the stage keys and `tokens_reported` are checked."""
    given = fields(words)
    tokens = given.get("tokens_reported")
    if tokens is not None and tokens != "unknown" and not tokens.isdigit():
        return f"tokens_reported must be a count or `unknown`, got {tokens!r}"
    if not words or words[0] not in KEYS:
        return None
    if given.get("stage") not in STAGES:
        return f"{words[0]} needs stage=<{'|'.join(STAGES)}>"
    if words[0] == "stage_end" and tokens is None:
        return "stage_end needs tokens_reported=<n|unknown>"
    for key in ("workers", "personas"):
        if key in given and not given[key].isdigit():
            return f"{key} must be a count, got {given[key]!r}"
    return None


def tokens_text(value: str | None) -> str:
    if value is None or not value.isdigit():
        return "tokens unknown"
    count = int(value)
    return f"{round(count / 1000)}k tokens" if count >= 1000 else f"{count} tokens"


def cost_line(given: dict[str, str]) -> str:
    """`implement: 3 workers, 410k tokens`; a missing count is left out, an unreported total is `unknown`."""
    stage = given.get("stage", "?")
    noun = STAGES.get(stage, "workers")
    count = given.get(noun)
    parts = ([f"{count} {noun}"] if count else []) + [tokens_text(given.get("tokens_reported"))]
    return f"{stage}: " + ", ".join(parts)


def stage_ends(progress: str) -> dict[str, dict[str, str]]:
    """The last `stage_end` per stage in a PROGRESS.md."""
    latest: dict[str, dict[str, str]] = {}
    for line in progress.splitlines():
        found = METRIC.search(line)
        if found and found.group(1) == "stage_end":
            given = fields(found.group(2).split())
            if given.get("stage") in STAGES:
                latest[given["stage"]] = given
    return latest


def task_summary(task_dir: Path) -> str:
    try:
        text = (task_dir / "PROGRESS.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    return "; ".join(cost_line(g) for g in stage_ends(text).values())


def print_cost(tasks_dir: Path) -> int:
    """One `<task>: <cost line>` per task that recorded a stage end."""
    if not tasks_dir.is_dir():
        print(f"error: no tasks directory: {tasks_dir}", file=sys.stderr)
        return 2
    rows = [(d.name, task_summary(d)) for d in sorted(tasks_dir.iterdir()) if d.is_dir()]
    rows = [(name, summary) for name, summary in rows if summary]
    print("\n".join(f"{name}: {summary}" for name, summary in rows) if rows else "no recorded stage costs")
    return 0
