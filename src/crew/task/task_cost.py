"""Usage per agent kind and harness, Cursor session tokens, and `crew ls --cost`, over `task_progress` entries.

A Cursor subagent's `agent_end` has `tokens=unknown`; a Cursor session's `cursor_stop` lines hold raw counts per
`stop`, read here without counting any twice. `crew ls --cost`, `crew report` and the TUI label each harness.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from crew.task.task_progress import (
    CURSOR_STOP,
    HARNESS_DEFAULT,
    STOP_COUNTS,
    Entry,
    agent_ends,
    count_text,
    fields,
    new_tokens,
    number,
    read_entries,
    stage_usage,
    sum_usage,
    usage_text,
)


def cursor_session_usage(entries: list[Entry], start: datetime | None = None) -> dict | None:
    """The Cursor sessions' `{"new", "cache_read", "stops", "conversations"}` from `cursor_stop` lines, or None.

    Whether a `stop`'s counts are that loop's or the conversation's running total is not established, so each line
    holds the raw counts and this reader takes, per conversation in file order, each count's rise over the previous
    stop (all of it after a fall). A running total sums to its last value and per-loop counts to at most their sum,
    so no count is ever added twice. A `generation_id` already seen, and a line missing either id, are skipped; a
    conversation's stops are all on one task (`task_usage.record_stop`), so summing tasks counts none twice."""
    seen: set[str] = set()
    last: dict[str, dict[str, int]] = {}
    totals, stops = dict.fromkeys(STOP_COUNTS, 0), 0
    for entry in entries:
        words = entry.body.split()
        if entry.kind != "METRIC" or not words or words[0] != CURSOR_STOP:
            continue
        given = fields(words)
        generation, conversation = given.get("generation_id", ""), given.get("conversation_id", "")
        if not generation or not conversation or generation in seen:
            continue
        seen.add(generation)
        previous = last.get(conversation, dict.fromkeys(STOP_COUNTS, 0))
        counts = {key: number(given.get(key, 0)) for key in STOP_COUNTS}
        last[conversation] = counts
        if start is not None and (entry.at is None or entry.at < start):
            continue
        stops += 1
        for key in STOP_COUNTS:
            totals[key] += counts[key] - previous[key] if counts[key] >= previous[key] else counts[key]
    if not stops:
        return None
    return {"new": new_tokens(totals), "cache_read": totals["cache_read"], "stops": stops, "conversations": len(last)}


def agent_kinds(entries: list[Entry], start: datetime | None = None) -> dict[tuple[str, str], dict]:
    """`{(agent kind, harness): {runs, new (None when no run reported tokens), cache_read, tool_calls, seconds}}` over
    each agent's latest `agent_end` (`agent_ends`, unknown tokens included), for `crew ls --cost` and `crew report`.
    The kind is the entry's `persona` (a reviewer lens, a critic), else its `agent` type."""
    kinds: dict[tuple[str, str], dict] = {}
    for entry, given in agent_ends(entries, unknown=True):
        if start is not None and (entry.at is None or entry.at < start):
            continue
        key = (given.get("persona") or given.get("agent") or "?", given.get("harness") or HARNESS_DEFAULT)
        kind = kinds.setdefault(key, {"runs": 0, "new": None, "cache_read": 0, "tool_calls": 0, "seconds": 0.0})
        kind["runs"] += 1
        if given.get("tokens", "").isdigit():
            kind["new"] = (kind["new"] or 0) + new_tokens(given)
            kind["cache_read"] += number(given.get("cache_read", 0))
        kind["tool_calls"] += number(given.get("tool_calls", 0))
        kind["seconds"] += number(given.get("duration_ms", 0)) / 1000
    return kinds


def kind_text(name: tuple[str, str], data: Mapping[str, object]) -> str:
    """`crew-builder (cursor) 2 runs, tokens unknown, 31 tool calls, 12m`, or `... 1 run, new 7k, cache reads 60k`."""
    runs = number(data["runs"])
    parts = [f"{name[0]} ({name[1]}) {runs} run{'' if runs == 1 else 's'}"]
    if data["new"] is None:
        parts.append("tokens unknown")
    else:
        parts += [f"new {count_text(number(data['new']))}", f"cache reads {count_text(number(data['cache_read']))}"]
    if number(data["tool_calls"]):
        parts.append(f"{number(data['tool_calls'])} tool calls")
    seconds = float(str(data["seconds"]))
    if seconds:
        parts.append(f"{round(seconds / 60)}m" if seconds >= 60 else f"{round(seconds)}s")
    return ", ".join(parts)


def session_text(session: Mapping[str, object]) -> str:
    """`cursor sessions: new ~1.2M, cache reads ~3.4M (5 stops)`: approximate (`~`) until it is settled whether a
    `stop` reports per-loop counts (then this reads low) or running totals (then it is exact)."""
    return f"cursor sessions: new {count_text(number(session['new']), True)}, cache reads {count_text(number(session['cache_read']), True)} ({session['stops']} stops)"


def task_summary(task_dir: Path) -> str:
    """`new 790k, cache reads 401k; implement: 3 workers, new ~410k; ...; agents: crew-builder (claude-code) 1 run,
    ...; cursor sessions: ...`, or "" when no stage, agent or Cursor session recorded anything."""
    entries = read_entries(task_dir)
    stages, kinds, session = stage_usage(entries), agent_kinds(entries), cursor_session_usage(entries)
    parts = [usage_text(sum_usage(list(stages.values())))] if stages else []
    for stage, data in stages.items():
        count = [f"{data['count']} {data['noun']}"] if data["count"] else []
        parts.append(f"{stage}: " + ", ".join([*count, f"new {count_text(data['new'], data['approximate'])}"]))
    if kinds:
        parts.append("agents: " + " / ".join(kind_text(name, data) for name, data in sorted(kinds.items())))
    if session:
        parts.append(session_text(session))
    return "; ".join(parts)


def print_cost(tasks_dir: Path) -> int:
    """One `<task>: <cost line>` per task that recorded a stage, an agent or a Cursor session."""
    if not tasks_dir.is_dir():
        print(f"error: no tasks directory: {tasks_dir}", file=sys.stderr)
        return 2
    rows = [(d.name, task_summary(d)) for d in sorted(tasks_dir.iterdir()) if d.is_dir()]
    rows = [(name, summary) for name, summary in rows if summary]
    print("\n".join(f"{name}: {summary}" for name, summary in rows) if rows else "no recorded stage costs")
    return 0
