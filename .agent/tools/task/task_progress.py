"""The one owner of a task's PROGRESS.md: append and read entries, the BLOCKED, METRIC, cost and PR views.

An entry is `[<UTC stamp>] <KIND>: <body>` (`YYYY-MM-DDTHH:MM:SSZ`, `lib.clock`); legacy local stamps still parse.
`CREW_WORKFLOW`/`CREW_MEMBER` add a JSON suffix to a transition. `stage_start`/`stage_end ... tokens_reported=<n>`
and `agent_end ... tokens=<n>` are validated here; an `agent_end` counts toward the stage of the `stage_start` before
it and replaces that stage's `tokens_reported`. `task_usage_totals` is the one token measure (new and cache reads).
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lib.clock import parse_stamp, utc_stamp

STAGES = {"implement": "workers", "review": "personas"}
KEYS = ("stage_start", "stage_end")
AGENT_END = "agent_end"
AGENT_COUNTS = ("tokens", "input", "output", "cache_read", "cache_write")
NEW_FIELDS = ("input", "output", "cache_write")  # an agent's new tokens: every summed count but the cache reads
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


def number(value: object) -> int:
    """A count field (a digit string or an int) as an int; anything else is 0."""
    text = str(value)
    return int(text) if text.isdigit() else 0


def new_tokens(counts: Mapping[str, object]) -> int:
    """An agent's new tokens: input + output + cache_write, each already summed over its calls."""
    return sum(number(counts.get(key, 0)) for key in NEW_FIELDS)


def count_text(value: int | None, approximate: bool = False) -> str:
    """`1.1M`, `259k` or `512`, `~` first when approximate; `-` when unknown."""
    if value is None:
        return "-"
    text = f"{value / 1e6:.1f}M" if value >= 999_500 else f"{round(value / 1000)}k" if value >= 1000 else str(value)
    return ("~" if approximate else "") + text


def usage_text(usage: Mapping[str, object]) -> str:
    """`new 106k, cache reads 401k` for a `task_usage_totals` result."""
    return f"new {count_text(usage['new'], bool(usage['approximate']))}, cache reads {count_text(usage['cache_read'])}"


def sum_usage(items: list[Mapping[str, object]]) -> dict:
    """`new` and `cache_read` summed over `items` (None when no item knows it); approximate when any known `new` is."""
    news = [item["new"] for item in items if item["new"] is not None]
    reads = [item["cache_read"] for item in items if item["cache_read"] is not None]
    return {"new": sum(news) if news else None, "cache_read": sum(reads) if reads else None,
            "approximate": any(bool(item["approximate"]) for item in items if item["new"] is not None)}


def stage_usage(entries: list[Entry], start: datetime | None = None) -> dict[str, dict]:
    """Per stage: `new`, `cache_read`, `approximate`, `agents` (True when agents' entries counted), and `count`
    (agents, else the reported workers or personas) with its `noun`.

    A stage's agents (`agent_ends`: each id once) sum their `new_tokens` and `cache_read`. Each run of the stage (a
    `stage_start` to its `stage_end`) with no `agent_end` adds its `tokens_reported` as `new`, approximate (a final
    context, not a sum), with no cache reads. `start` keeps only the entries at or after it.
    """
    def kept(entry: Entry) -> bool:
        return start is None or (entry.at is not None and entry.at >= start)

    reported: dict[str, dict] = {}  # stage: the uncovered runs' summed `tokens_reported` and the last count
    covered: dict[str, bool] = {}  # stage: its current run has an `agent_end`
    current = UNSTAGED
    for entry in entries:
        words = entry.body.split()
        if entry.kind != "METRIC" or not words:
            continue
        given = fields(words)
        stage, tokens = given.get("stage", ""), given.get("tokens_reported", "")
        if words[0] == "stage_start" and stage in STAGES:
            current, covered[stage] = stage, False
        elif words[0] == AGENT_END and given.get("tokens", "").isdigit():
            covered[current] = True
        elif words[0] == "stage_end" and stage in STAGES and kept(entry):
            run = reported.setdefault(stage, {"new": None, "count": 0})
            run["count"] = number(given.get(STAGES[stage], 0)) or run["count"]
            if tokens.isdigit() and not covered.get(stage):
                run["new"] = (run["new"] or 0) + int(tokens)
            covered[stage] = False
    agents = [given for entry, given in agent_ends(entries) if kept(entry)]
    usage: dict[str, dict] = {}
    for stage in dict.fromkeys([*reported, *(agent["stage"] for agent in agents)]):
        mine = [agent for agent in agents if agent["stage"] == stage]
        run = reported.get(stage, {"new": None, "count": 0})
        items = [{"new": run["new"], "cache_read": None, "approximate": True}] if run["new"] is not None else []
        if mine:
            items.append({"new": sum(new_tokens(agent) for agent in mine), "approximate": False,
                          "cache_read": sum(number(agent.get("cache_read", 0)) for agent in mine)})
        usage[stage] = {**sum_usage(items), "agents": bool(mine), "count": len(mine) if mine else run["count"],
                        "noun": STAGES.get(stage, "workers")}
    return usage


def task_usage_totals(entries: list[Entry], start: datetime | None = None) -> dict:
    """One task's `{"new", "cache_read", "approximate"}`: its `stage_usage` summed, the one measure `crew ls --cost`,
    `crew ls --json`, `crew report` and the TUI show."""
    return sum_usage(list(stage_usage(entries, start).values()))


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


def task_summary(task_dir: Path) -> str:
    """`new 790k, cache reads 401k; implement: 3 workers, new ~410k; ...`, or "" when no stage recorded tokens."""
    stages = stage_usage(read_entries(task_dir))
    if not stages:
        return ""
    parts = [usage_text(sum_usage(list(stages.values())))]
    for stage, data in stages.items():
        count = [f"{data['count']} {data['noun']}"] if data["count"] else []
        parts.append(f"{stage}: " + ", ".join([*count, f"new {count_text(data['new'], data['approximate'])}"]))
    return "; ".join(parts)


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
KINDS = ("TRANSITION", "METRIC", "BLOCKED", "WORKTREE", "PR", "WARN", "SHIP")
# Audit, preference, PR, warning and ship-step lines never end a block (a stage_start does).
NEUTRAL = ("METRIC", "WORKTREE", "PR", "WARN", "SHIP")
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


def latest(task_dir: Path, entries: list[Entry] | None = None) -> datetime | None:
    """The newest stamped entry's time, legacy and UTC lines compared on one clock; `entries` when already read."""
    times = [entry.at for entry in (read_entries(task_dir) if entries is None else entries) if entry.at]
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


def pr_urls(task_dir: Path, entries: list[Entry] | None = None) -> list[str]:
    """The task's PR list, oldest first: every PR URL in a `PR:` entry or after `PR opened:`, once each.

    One store, two writers through `append_pr` and the DONE transition: `mark-done` writes `PR opened:
    <url>` in that transition and a `PR:` entry for a later PR, reconcile a `PR:` entry for a PR it
    found on the task's branch. `PR opened:` counts only in a transition or an untyped legacy line, so
    a BLOCKED reason that quotes one adds nothing. `entries` are the task's entries when the caller already read them.
    """
    found: list[str] = []
    for entry in read_entries(task_dir) if entries is None else entries:
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
