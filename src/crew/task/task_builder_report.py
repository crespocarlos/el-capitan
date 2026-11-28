"""A builder's reply saved as its task's report: by the subagent-stop hook, or by `crew-task.py report save`.

From the `## Implementation Report` heading on, the reply goes atomically to `REPORT.md`, or for a batch to
`REPORT.part-<a>-<b>.md` (the final batch: both), each beside `<name>.provenance.json`. A report that fails
`report-check` against `gates.json` is still saved, with one WARN entry in PROGRESS.md; a run it cannot save says why.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from crew.lib.clock import utc_stamp
from crew.lib.files import atomic_write
from crew.task.task_progress import append_entry
from crew.task.task_usage import TASK_LINE, is_task, task_of
from crew.task.task_verify_report import load_gates, problems

HEADING = re.compile(r"^## Implementation Report[ \t]*$", re.M)
RANGE_LINE = re.compile(r"^TASK_RANGE:[ \t]*(\d+)-(\d+)([ \t]+final)?[ \t]*$")
BUILDER = "crew-builder"
SCHEMA_VERSION = 1
UNSAVED = "no report saved: "

TaskRange = tuple[int, int, bool]  # first task, last task, whether this batch is the final one


def report_names(task_range: TaskRange | None) -> list[str]:
    """The files one reply is saved as: `REPORT.md`, a batch's part report, or the final batch's part and REPORT.md."""
    if task_range is None:
        return ["REPORT.md"]
    part = f"REPORT.part-{task_range[0]}-{task_range[1]}.md"
    return [part, "REPORT.md"] if task_range[2] else [part]


def save_report(task_dir: Path, reply: str, harness: str, task_range: TaskRange | None = None, agent_id: str | None = None, model: str | None = None) -> str:
    """Save the report part of `reply`; the one line saying what happened."""
    heading = HEADING.search(reply)
    if not heading:
        return UNSAVED + "the reply has no `## Implementation Report` heading"
    if not is_task(task_dir):
        return UNSAVED + f"{task_dir} is not a task directory under ~/.agent/tasks"
    names = report_names(task_range)
    text = reply[heading.start() :].rstrip() + "\n"
    found = problems(text, load_gates(task_dir / "gates.json"), lenient=False)
    for name in names:
        atomic_write(task_dir / name, text)
        record = {
            "schema_version": SCHEMA_VERSION,
            "report": name,
            "harness": harness,
            "agent_id": agent_id or None,
            "model": model or None,
            "time": utc_stamp(),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "bytes": len(text.encode()),
            "report_check": "fail" if found else "ok",
        }
        atomic_write(task_dir / f"{name.removesuffix('.md')}.provenance.json", json.dumps(record, indent=2) + "\n")
    saved = " and ".join(str(task_dir / name) for name in names)
    if not found:
        return f"saved {saved} (report-check ok)"
    more = f" (+{len(found) - 1} more)" if len(found) > 1 else ""
    append_entry(task_dir, "WARN", f"{names[0]} fails report-check: {found[0]}{more}")
    return f"saved {saved} (report-check FAIL, WARN in PROGRESS.md)"


def header(prompt: str) -> list[str]:
    """The prompt's header: the run of non-blank lines that holds its `crew-task:` line."""
    lines = prompt.splitlines()
    at = next((index for index, line in enumerate(lines) if TASK_LINE.match(line)), None)
    if at is None:
        return []
    start, end = at, at
    while start > 0 and lines[start - 1].strip():
        start -= 1
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return lines[start : end + 1]


def task_range_of(prompt: str) -> TaskRange | None:
    """The `TASK_RANGE: <a>-<b>[ final]` line of the header; ValueError when it holds more than one."""
    found = [match for match in map(RANGE_LINE.match, header(prompt)) if match]
    if len(found) > 1:
        raise ValueError(f"{len(found)} TASK_RANGE lines in the prompt's header; write one")
    return (int(found[0].group(1)), int(found[0].group(2)), bool(found[0].group(3))) if found else None


def capture_builder(payload: dict, prompt: str, reply: str, model: str | None, harness: str = "claude-code") -> str:
    """The hook's save for a `crew-builder` run, into the task its `crew-task:` line names; "" for any other agent.
    `payload` carries `agent_type` and `agent_id` in either harness (`review_capture.normalized`)."""
    if str(payload.get("agent_type") or "").rsplit(":", 1)[-1] != BUILDER:
        return ""
    task_dir = task_of(prompt, None)
    if task_dir is None:
        return UNSAVED + "the dispatch prompt has no `crew-task: <TASK_DIR>` line"
    try:
        task_range = task_range_of(prompt)
    except ValueError as error:
        return UNSAVED + str(error)
    return save_report(task_dir, reply, harness, task_range, str(payload.get("agent_id") or ""), model)


def parse_range(value: str) -> tuple[int, int]:
    found = re.fullmatch(r"(\d+)-(\d+)", value)
    if not found:
        raise argparse.ArgumentTypeError("write the range as <first>-<last>, for example 1-6")
    return int(found.group(1)), int(found.group(2))


def main(argv: list[str]) -> int:
    """`crew-task.py report save <TASK_DIR>`: the builder's reply on stdin, saved as the hook saves it."""
    parser = argparse.ArgumentParser(prog="crew-task.py report", description="Save a builder's reply (stdin) as its task's REPORT.md.")
    commands = parser.add_subparsers(dest="action", required=True)
    save = commands.add_parser("save", help="save the reply on stdin; exit 1 when nothing was saved")
    save.add_argument("task_dir", type=Path, metavar="TASK_DIR")
    save.add_argument("--range", type=parse_range, default=None, metavar="FIRST-LAST", help="the batch's TASK_RANGE: saves REPORT.part-<first>-<last>.md")
    save.add_argument("--final", action="store_true", help="with --range, the final batch: also saves REPORT.md")
    save.add_argument("--harness", default="cursor", help="recorded in the provenance (default: cursor)")
    args = parser.parse_args(argv)
    if args.final and args.range is None:
        parser.error("--final needs --range")
    task_range = (*args.range, args.final) if args.range else None
    line = save_report(args.task_dir, sys.stdin.read(), args.harness, task_range)
    print(f"report: {line}")
    return 0 if line.startswith("saved ") else 1
