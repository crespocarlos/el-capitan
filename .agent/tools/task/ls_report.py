"""`crew-ls.py --report`: what happened over a window, over the rows `ls_data` loads and filters.

Tasks opened (`created_at`, else the first PROGRESS entry) and closed (a `→ DONE` transition), verdicts
of the tasks active in the window, findings by label with the fixed rate (`<task>/review/outcomes.jsonl`,
the last record per fingerprint), stage runs, tokens and durations (`stage_start`/`stage_end`), review
run sizes, and tool failures from the memory `.sessions` telemetry (no repository, so never filtered).
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from task_gc import DEFAULTS, ConfigError, Places, load_config
from task_progress import fields, read_entries
from task_state import TaskState, head

from lib.clock import parse_stamp

SINCE = re.compile(r"^(\d+)d$")
QUEUE = "review-queue.jsonl"


def since_days(text: str) -> int:
    """`30d` as 30; a ValueError names the accepted form."""
    found = SINCE.match(text.strip())
    if not found:
        raise ValueError(f"--since takes a day count such as 30d, not {text!r}")
    return int(found.group(1))


def moment(text: object) -> datetime | None:
    """An aware time from a stamp, an ISO string, or an ISO string ending in `Z` (Python 3.9 reads none of those)."""
    if not isinstance(text, str):
        return None
    return parse_stamp(text) or (parse_stamp(text[:-1] + "+00:00") if text.endswith("Z") else None)


def in_window(at: datetime | None, start: datetime) -> bool:
    """True when `at` is known and not before `start`."""
    return at is not None and at >= start


def opened_at(r: TaskState, entries: list) -> datetime | None:
    found = moment(r.meta.get("created_at"))
    if found:
        return found
    stamped = [entry.at for entry in entries if entry.at]
    return min(stamped) if stamped else None


def closed_at(entries: list) -> datetime | None:
    done = [e.at for e in entries if e.kind == "TRANSITION" and e.at and re.search(r"(→|->)\s*DONE\b", e.body)]
    return max(done) if done else None


def stage_runs(entries: list, start: datetime) -> list[dict]:
    """One record per `stage_end` in the window: stage, tokens (None when unreported), seconds since its start."""
    opened: dict[str, datetime] = {}
    runs = []
    for entry in entries:
        words = entry.body.split()
        if entry.kind != "METRIC" or not words or words[0] not in ("stage_start", "stage_end") or not entry.at:
            continue
        given = fields(words)
        stage = given.get("stage", "?")
        if words[0] == "stage_start":
            opened[stage] = entry.at
            continue
        if entry.at >= start:
            began = opened.pop(stage, None)
            tokens = given.get("tokens_reported", "")
            runs.append({"stage": stage, "tokens": int(tokens) if tokens.isdigit() else None,
                         "seconds": (entry.at - began).total_seconds() if began else None})
    return runs


def review_runs(entries: list, start: datetime) -> list[dict]:
    """The `review run=` METRIC lines in the window, with their input and output byte counts."""
    return [{key: int(value) for key, value in fields(e.body.split()).items() if value.isdigit()}
            for e in entries if e.kind == "METRIC" and e.body.startswith("review run=") and in_window(e.at, start)]


def findings(rows: list[TaskState], start: datetime) -> dict[str, Counter]:
    """`{label: Counter(outcome)}` over the decisions recorded in the window, the last record per fingerprint."""
    decided: dict[tuple[str, str], tuple[str, str]] = {}
    for r in rows:
        path = r.task / "review" / "outcomes.jsonl"
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            at = moment(record.get("ts")) if isinstance(record, dict) else None
            if at and at >= start and isinstance(record.get("fingerprint"), str):
                label, outcome = str(record.get("label") or "?"), str(record.get("outcome") or "?")
                decided[(r.uuid, record["fingerprint"])] = (label, outcome)
    labels: dict[str, Counter] = {}
    for label, outcome in decided.values():
        labels.setdefault(label, Counter())[outcome] += 1
    return labels


def tool_failures(memory: Path, start: datetime) -> dict:
    """Tool calls and failures per tool from the session telemetry in the window."""
    calls, failed = 0, Counter()
    sessions = memory / ".sessions"
    for path in sorted(sessions.glob("*.jsonl")) if sessions.is_dir() else []:
        if path.name == QUEUE or path.stat().st_mtime < start.timestamp():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            at = moment(record.get("ts")) if isinstance(record, dict) else None
            if at and at >= start:
                calls += 1
                failed[str(record.get("tool") or "?")] += 1 if record.get("failure") is True else 0
    return {"calls": calls, "failures": sum(failed.values()), "by_tool": {k: v for k, v in failed.most_common() if v}}


def gather(rows: list[TaskState], days: int, memory: Path | None = None, now: datetime | None = None) -> dict:
    """The report over `rows` (already filtered by repository) for the last `days` days."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    places = Places.here()
    memory = memory or places.memory
    entries = {r.task: read_entries(r.task) for r in rows}
    active = [r for r in rows if r.activity <= days]
    runs = [run for r in rows for run in stage_runs(entries[r.task], start)]
    stages = {}
    for stage in sorted({run["stage"] for run in runs}):
        mine = [run for run in runs if run["stage"] == stage]
        durations = [run["seconds"] for run in mine if run["seconds"] is not None]
        stages[stage] = {"runs": len(mine), "tokens": sum(run["tokens"] or 0 for run in mine),
                         "unreported": sum(1 for run in mine if run["tokens"] is None),
                         "median_seconds": statistics.median(durations) if durations else None}
    labels = findings(rows, start)
    reviews = [run for r in rows for run in review_runs(entries[r.task], start)]
    try:
        policy = load_config(places.agent)["gc"]
    except ConfigError:
        policy = DEFAULTS["gc"]
    retention = min(policy["archive_days"], policy["sessions_days"])
    return {
        "days": days, "since": start.strftime("%Y-%m-%d"),
        "retention_note": (f"tasks crew gc archived (after {policy['archive_days']} days) and session files it removed "
                           f"(after {policy['sessions_days']} days) are not counted") if days > retention else "",
        "opened": sum(1 for r in rows if in_window(opened_at(r, entries[r.task]), start)),
        "closed": sum(1 for r in rows if in_window(closed_at(entries[r.task]), start)),
        "open_now": sum(1 for r in rows if head(r) != "DONE"),
        "verdicts": dict(Counter(r.verdict.lower() if r.verdict != "?" else "none" for r in active).most_common()),
        "findings": {label: dict(counts) for label, counts in sorted(labels.items())},
        "stages": stages,
        "reviews": {"runs": len(reviews), "in_bytes": sum(run.get("in_bytes", 0) for run in reviews),
                    "out_bytes": sum(run.get("out_bytes", 0) for run in reviews)},
        "tools": tool_failures(memory, start),
    }


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "duration unknown"
    minutes = round(seconds / 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def rate(fixed: int, total: int) -> str:
    return f"{fixed} fixed ({round(100 * fixed / total)}%)" if total else "none"


def render(report: dict, scope: str) -> list[str]:
    """The report as one screen of text."""
    lines = [f"crew report: last {report['days']} days (since {report['since']}), {scope}",
             f"tasks: {report['opened']} opened, {report['closed']} closed, {report['open_now']} open now"]
    verdicts = ", ".join(f"{k} {v}" for k, v in report["verdicts"].items()) or "none"
    lines.append(f"review verdicts (tasks active in the window): {verdicts}")
    total = sum(sum(c.values()) for c in report["findings"].values())
    fixed = sum(c.get("fixed", 0) for c in report["findings"].values())
    lines.append(f"findings decided: {total}, {rate(fixed, total)}")
    for label, counts in report["findings"].items():
        lines.append(f"  {label:<16} {sum(counts.values()):>4}  {rate(counts.get('fixed', 0), sum(counts.values()))}")
    for stage, data in report["stages"].items():
        unreported = f" ({data['unreported']} unreported)" if data["unreported"] else ""
        tokens = f"{round(data['tokens'] / 1000)}k tokens{unreported}"
        lines.append(f"stage {stage}: {data['runs']} run(s), {tokens}, median {duration(data['median_seconds'])}")
    if not report["stages"]:
        lines.append("stages: no stage_end recorded in the window")
    reviews = report["reviews"]
    sizes = f"{reviews['in_bytes'] / 1e6:.1f} MB in, {reviews['out_bytes'] / 1e6:.1f} MB out"
    lines.append(f"review runs: {reviews['runs']}, {sizes}")
    tools = report["tools"]
    by_tool = ", ".join(f"{k} {v}" for k, v in tools["by_tool"].items())
    lines.append(f"tool failures (session telemetry, all repos): {tools['failures']} of {tools['calls']} calls"
                 + (f" ({by_tool})" if by_tool else ""))
    if report.get("retention_note"):
        lines.append(f"note: the window is longer than the retention policy: {report['retention_note']}")
    return lines
