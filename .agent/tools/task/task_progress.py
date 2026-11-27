"""The one owner of a task's PROGRESS.md: append and read entries, the BLOCKED, METRIC, cost and PR views.

An entry is `[<UTC stamp>] <KIND>: <body>` (`YYYY-MM-DDTHH:MM:SSZ`, `lib.clock`); legacy local stamps
still parse. `CREW_WORKFLOW`/`CREW_MEMBER` add a JSON suffix to a transition. A stage cost line
(`stage_start`/`stage_end ... tokens_reported=<n|unknown>`) and `agent_end ... tokens=<n>` are validated here;
an `agent_end` counts toward the stage of the `stage_start` before it, and replaces that stage's `tokens_reported`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lib.clock import parse_stamp, utc_stamp

STAGES = {"implement": "workers", "review": "personas"}
KEYS = ("stage_start", "stage_end")
METRIC = re.compile(r"METRIC:\s+(stage_start|stage_end|agent_end)\b(.*)$")
AGENT_END = "agent_end"
AGENT_COUNTS = ("tokens", "input", "output", "cache_read", "cache_write")
UNSTAGED = "other"  # the stage of an `agent_end` with no `stage_start` before it


def fields(words: list[str]) -> dict[str, str]:
    return {k: v for k, _, v in (word.partition("=") for word in words if "=" in word)}


def validate(words: list[str]) -> str | None:
    """The problem with a metric payload, or None. Only the stage keys and `tokens_reported` are checked."""
    given = fields(words)
    tokens = given.get("tokens_reported")
    if tokens is not None and tokens != "unknown" and not tokens.isdigit():
        return f"tokens_reported must be a count or `unknown`, got {tokens!r}"
    if words and words[0] == AGENT_END:
        if "tokens" not in given:
            return "agent_end needs tokens=<n>"
        bad = [key for key in AGENT_COUNTS if key in given and not given[key].isdigit()]
        return f"{bad[0]} must be a count, got {given[bad[0]]!r}" if bad else None
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
    """`implement: 3 workers, 410k tokens` (`, 12k output` from `agent_end`); a missing count is left out, an
    unreported total is `unknown`."""
    stage = given.get("stage", "?")
    noun = STAGES.get(stage, "workers")
    count = given.get(noun)
    output = given.get("output", "")
    parts = ([f"{count} {noun}"] if count else []) + [tokens_text(given.get("tokens_reported"))]
    parts += [tokens_text(output).replace("tokens", "output")] if output.isdigit() else []
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


def agent_ends(entries: list[Entry]) -> list[tuple[Entry, dict[str, str]]]:
    """The one stage attribution of `agent_end` entries, for `crew ls --cost` and `crew report`: each agent's latest
    entry (one per `agent_id`; a resumed agent's later stop replaces its earlier one; an entry with no id counts
    alone), its fields with `stage`: the last `stage_start` before it, else `other`."""
    stage, latest = UNSTAGED, {}
    for index, entry in enumerate(entries):
        words = entry.body.split()
        if entry.kind != "METRIC" or not words:
            continue
        given = fields(words)
        if words[0] == "stage_start" and given.get("stage") in STAGES:
            stage = given["stage"]
        elif words[0] == AGENT_END and given.get("tokens", "").isdigit():
            key = given.get("agent_id") or f"#{index}"
            latest.pop(key, None)
            latest[key] = (entry, {**given, "stage": stage})
    return list(latest.values())


def stage_costs(progress: str) -> dict[str, dict[str, str]]:
    """The cost fields per stage: the last `stage_end`, its tokens replaced by any `agent_end` total (each agent's
    final context, never the summed cache reads), with the summed `output` beside it."""
    costs = stage_ends(progress)
    agents = [given for _, given in agent_ends([parse_entry(line) for line in progress.splitlines() if line.strip()])]
    for stage in dict.fromkeys(agent["stage"] for agent in agents):
        mine = [agent for agent in agents if agent["stage"] == stage]
        given = {"stage": stage, **costs.get(stage, {}), "tokens_reported": str(sum(int(a["tokens"]) for a in mine)),
                 "output": str(sum(int(a.get("output", "0")) for a in mine if a.get("output", "0").isdigit()))}
        given.setdefault(STAGES.get(stage, "workers"), str(len(mine)))
        costs[stage] = given
    return costs


def task_summary(task_dir: Path) -> str:
    return "; ".join(cost_line(g) for g in stage_costs(read_text(task_dir)).values())


def print_cost(tasks_dir: Path) -> int:
    """One `<task>: <cost line>` per task that recorded a stage end."""
    if not tasks_dir.is_dir():
        print(f"error: no tasks directory: {tasks_dir}", file=sys.stderr)
        return 2
    rows = [(d.name, task_summary(d)) for d in sorted(tasks_dir.iterdir()) if d.is_dir()]
    rows = [(name, summary) for name, summary in rows if summary]
    print("\n".join(f"{name}: {summary}" for name, summary in rows) if rows else "no recorded stage costs")
    return 0


PROGRESS_FILE = "PROGRESS.md"
KINDS = ("TRANSITION", "METRIC", "BLOCKED", "WORKTREE", "PR")
NEUTRAL = ("METRIC", "WORKTREE", "PR")  # audit, preference and PR lines never end a block (a stage_start does)
# The one PR URL shape: read into a PR list, accepted by `mark-done`, kept from a `gh pr list` answer.
GITHUB_PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")


@dataclass(frozen=True)
class Entry:
    at: datetime | None  # aware UTC; None for a line with no stamp
    kind: str  # one of KINDS, or "" for any other line
    body: str  # the text after `KIND: `, or the whole text
    text: str  # the line after its stamp


def parse_entry(line: str) -> Entry:
    """One line as an entry; a line with no readable stamp keeps its text and has no time."""
    at, text = None, line.strip()
    if text.startswith("[") and "] " in text:
        stamp, rest = text[1:].split("] ", 1)
        at = parse_stamp(stamp)
        text = rest if at else text
    kind, _, body = text.partition(": ")
    return Entry(at, kind, body, text) if kind in KINDS else Entry(at, "", text, text)


def read_text(task_dir: Path) -> str:
    """The raw file, or "" when it is missing or unreadable."""
    try:
        return (task_dir / PROGRESS_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_entries(task_dir: Path) -> list[Entry]:
    """Every non-blank line, in file order."""
    return [parse_entry(line) for line in read_text(task_dir).splitlines() if line.strip()]


def latest(task_dir: Path) -> datetime | None:
    """The newest stamped entry's time, legacy and UTC lines compared on one clock."""
    times = [entry.at for entry in read_entries(task_dir) if entry.at]
    return max(times) if times else None


def append_entry(task_dir: Path, kind: str, body: str) -> None:
    """Append one stamped `KIND: body` line; raises `FileNotFoundError` for a missing task directory."""
    if not task_dir.is_dir():
        raise FileNotFoundError(f"task_dir does not exist: {task_dir}")
    with (task_dir / PROGRESS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(f"[{utc_stamp()}] {kind}: {body}\n")


def append_transition(task_dir: Path, transition: str) -> None:
    workflow = os.environ.get("CREW_WORKFLOW", "")
    crew = os.environ.get("CREW_MEMBER", "")
    suffix = ""
    if workflow or crew:
        step = transition.split("→", 1)[-1].strip()
        suffix = " " + json.dumps({"step": step, "workflow": workflow or None, "crew": crew or None},
                                  separators=(",", ":"))
    append_entry(task_dir, "TRANSITION", transition + suffix)


def append_metric(task_dir: Path, payload: str) -> None:
    """Append one audit-only METRIC line; raises `ValueError` naming an empty or invalid payload."""

    if not payload.strip():
        raise ValueError("empty payload")
    problem = validate(payload.split())
    if problem:
        raise ValueError(problem)
    append_entry(task_dir, "METRIC", payload.strip())


def append_blocked(task_dir: Path, reason: str) -> None:
    """One `BLOCKED: <reason>` line; a reason spanning lines is collapsed to one."""
    append_entry(task_dir, "BLOCKED", " ".join(reason.split()))


def pr_urls(task_dir: Path) -> list[str]:
    """The task's PR list, oldest first: every PR URL in a `PR:` entry or after `PR opened:`, once each.

    One store, two writers through `append_pr` and the DONE transition: `mark-done` writes `PR opened:
    <url>` in that transition and a `PR:` entry for a later PR, reconcile a `PR:` entry for a PR it
    found on the task's branch. `PR opened:` counts only in a transition or an untyped legacy line, so
    a BLOCKED reason that quotes one adds nothing.
    """
    found: list[str] = []
    for entry in read_entries(task_dir):
        if entry.kind == "PR":
            text = entry.body
        elif entry.kind in ("TRANSITION", ""):
            text = entry.text.partition("PR opened:")[2]
        else:
            continue
        found.extend(url for url in (match.group(0) for match in GITHUB_PR_URL.finditer(text)) if url not in found)
    return found


def append_pr(task_dir: Path, url: str) -> bool:
    """Add `url` to the task's PR list; False when it is already there."""
    if url in pr_urls(task_dir):
        return False
    append_entry(task_dir, "PR", url)
    return True


def append_worktree(task_dir: Path, choice: str, marker: object) -> None:
    append_entry(task_dir, "WORKTREE", f"{choice} (asked once; recorded in {marker})")


def has_metric(task_dir: Path, prefix: str) -> bool:
    """True when a METRIC entry's payload starts with `prefix`."""
    return any(entry.kind == "METRIC" and entry.body.startswith(prefix) for entry in read_entries(task_dir))


def blocked_reason(task_dir: Path) -> str:
    """The reason of the last BLOCKED entry when no later entry ends it, else an empty string."""
    for entry in reversed(read_entries(task_dir)):
        if entry.kind in NEUTRAL and "stage_start" not in entry.body:
            continue
        return entry.body.strip() if entry.kind == "BLOCKED" else ""
    return ""
