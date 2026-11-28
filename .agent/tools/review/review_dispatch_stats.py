"""`dispatch-bytes` and `cache-report`: what a prepared dispatch carries, and what a review run's personas paid for it.

`dispatch-bytes DIR` prints each prompt's bytes, its repository guidance bytes and the prefix it shares with the others:
a review directory's `<persona>.in.md`, or a task's `dispatch/*.md` and `spec-agents/*/*.prompt.md`. `cache-report`
reads one review run's METRIC lines: per persona its raw `agent_end` counts, its first call's cache read above the first
persona's own (the baseline every agent type shares), and the wall time from first dispatch to last end.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from assemble_inputs import PERSONAS
from review_records import common_prefix
from task_progress import fields, read_entries

from lib.clock import parse_stamp

COUNTS = ("cache_read", "cache_write", "input", "first_cache_read", "first_cache_write", "first_input")
# Anchored at line starts, so a quoted diff line (`+`, `-` or a space first) never matches; the last match counts.
GUIDANCE = re.compile(rb'^<guidance kind="[^"]*" cap="\d+">\n.*?^</guidance>\n?', re.S | re.M)
# A package written before the `<guidance>` element: its section runs to the next package separator.
LEGACY_GUIDANCE = re.compile(rb"^# Repository guidance\n.*?(?=\n---\n\n|\Z)", re.S | re.M)


def add_stats_parsers(commands) -> None:
    sizes = commands.add_parser("dispatch-bytes", help="bytes per dispatch prompt: total, guidance, shared prefix")
    sizes.add_argument("dir", type=Path, help="a review directory, or a task directory with dispatch/ or spec-agents/")
    sizes.add_argument("--json", action="store_true")
    cache = commands.add_parser("cache-report", help="per persona of one review run: cache counts and wall time")
    cache.add_argument("--task-dir", type=Path, required=True)
    cache.add_argument("--run", default="", help="the review run (its directory name); default: the latest")
    cache.add_argument("--json", action="store_true")


def prompts(folder: Path) -> list[Path]:
    """The dispatch prompts under `folder`, review packages first."""
    found = sorted(folder.glob("*.in.md"))
    return found or sorted([*folder.glob("dispatch/*.md"), *folder.glob("spec-agents/*/*.prompt.md")])


def guidance_bytes(text: bytes) -> int:
    found = GUIDANCE.findall(text) or LEGACY_GUIDANCE.findall(text)
    return len(found[-1]) if found else 0


def measure(folder: Path) -> dict:
    files = prompts(folder)
    texts = [path.read_bytes() for path in files]
    shared = common_prefix(texts)
    rows = [{"dispatch": path.name, "bytes": len(text), "guidance": guidance_bytes(text), "shared_prefix": shared}
            for path, text in zip(files, texts)]
    return {"dir": str(folder), "rows": rows, "total": sum(len(text) for text in texts),
            "guidance": sum(row["guidance"] for row in rows), "shared_prefix": shared}


def dispatch_bytes(args: argparse.Namespace) -> int:
    result = measure(args.dir)
    if not result["rows"]:
        print(f"dispatch-bytes: no dispatch prompt under {args.dir}")
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"{'dispatch':<32} {'bytes':>8} {'guidance':>9} {'shared_prefix':>14}")
    for row in result["rows"]:
        print(f"{row['dispatch']:<32} {row['bytes']:>8} {row['guidance']:>9} {row['shared_prefix']:>14}")
    print(f"{'total':<32} {result['total']:>8} {result['guidance']:>9}")
    return 0


def run_entries(task_dir: Path, run: str) -> tuple[dict, list]:
    """`(the run's review line fields, [(entry, fields)] of the lens agent_ends of that run)`: those after the
    previous `review run=` line and before the chosen one, which `persist` writes once its personas have answered."""
    entries = read_entries(task_dir)
    lines = [(index, fields(e.body.split())) for index, e in enumerate(entries)
             if e.kind == "METRIC" and e.body.startswith("review run=")]
    chosen = [position for position, item in enumerate(lines) if not run or item[1].get("run") == run]
    if not chosen:
        raise ValueError(f"no `review run={run or '...'}` METRIC line in {task_dir}")
    at, line = lines[chosen[-1]]
    begin = lines[chosen[-1] - 1][0] if chosen[-1] else -1
    lenses = {f"reviewer-{persona}" for persona in PERSONAS}
    agents = [(e, fields(e.body.split())) for e in entries[begin + 1:at]
              if e.kind == "METRIC" and e.body.startswith("agent_end ")]
    latest = {given.get("agent_id") or str(i): (e, given) for i, (e, given) in enumerate(agents)
              if given.get("agent") in lenses}
    return line, list(latest.values())


def stamp(given: dict) -> datetime | None:
    return parse_stamp(given["started"]) if given.get("started") else None


def dispatched(item: tuple) -> tuple[bool, float]:
    """Sort key: the agent's dispatch (`started=`), else its end; agents with neither last."""
    moment = stamp(item[1]) or item[0].at
    return moment is None, moment.timestamp() if moment else 0.0


def count(given: dict, key: str) -> int | None:
    value = given.get(key)
    return int(value) if value and value.isdigit() else None


def report(task_dir: Path, run: str) -> dict:
    line, agents = run_entries(task_dir, run)
    agents.sort(key=dispatched)
    baseline = count(agents[0][1], "first_cache_read") if agents else None
    rows = []
    for order, (entry, given) in enumerate(agents, 1):
        first = count(given, "first_cache_read")
        rows.append({"persona": given.get("persona"), "order": order, "started": given.get("started"),
                     "ended": entry.at.isoformat() if entry.at else None,
                     **{key: count(given, key) for key in COUNTS}, "harness": given.get("harness"),
                     "above_baseline": None if first is None or baseline is None else first - baseline})
    starts = [stamp(given) for _, given in agents if stamp(given)]
    ends = [entry.at for entry, _ in agents if entry.at]
    wall = round((max(ends) - min(starts)).total_seconds()) if starts and ends else None
    return {"run": line.get("run"), "shared_prefix": int(line.get("shared_prefix") or 0), "baseline": baseline,
            "agents": rows, "wall_s": wall}


def cell(value: object) -> str:
    return "?" if value is None else str(value)


def cache_report(args: argparse.Namespace) -> int:
    result = report(args.task_dir, args.run)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"run {result['run']}: shared_prefix={result['shared_prefix']} bytes; baseline (the first persona's "
          f"first_cache_read) {cell(result['baseline'])} tokens")
    print(f"{'#':>2} {'persona':<15} {'cache_read':>11} {'cache_write':>11} {'input':>7} {'first_read':>10} "
          f"{'first_write':>11} {'above_baseline':>14}")
    for row in result["agents"]:
        print(f"{row['order']:>2} {row['persona'] or '?':<15} {cell(row['cache_read']):>11} "
              f"{cell(row['cache_write']):>11} {cell(row['input']):>7} {cell(row['first_cache_read']):>10} "
              f"{cell(row['first_cache_write']):>11} {cell(row['above_baseline']):>14}")
    wall = "unknown (no started= on its agent_end lines)" if result["wall_s"] is None else f"{result['wall_s']} s"
    print(f"wall time, first dispatch to last agent_end: {wall}")
    return 0
