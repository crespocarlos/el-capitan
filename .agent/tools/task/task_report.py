"""Rendering task state for `crew-ls.py` (table, `--tsv`, JSON, the landed section) and `reconcile`.

Rendering never writes, so a listing failure is a display problem; `reconcile` applies holds and
statuses through `task_state`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from ls_data import landed_lines, landed_rows, snapshot
from task_progress import blocked_reason
from task_state import TaskState, decide, head, load_rules, name, set_status
from task_status import STATUS, StatusError, token

from lib.output import json_payload, print_lines, rows_limit

OPEN_ORDER = ["IMPLEMENTING", "APPROVED", "DRAFTING", "ON-HOLD"]


def state_label(r: TaskState) -> str:
    if head(r) == "ON-HOLD":
        was = re.search(r"was ([A-Za-z-]+)", r.status)
        return f"ON-HOLD (was {was.group(1)})" if was else "ON-HOLD"
    return head(r) or "?"


def table_rows(rows: list[TaskState], show_done: bool, markdown: bool) -> list[tuple[str, ...]]:
    """The table header plus one row per displayed spec, longest-lived first within each state."""
    def rank(r: TaskState) -> int:
        return OPEN_ORDER.index(head(r)) if head(r) in OPEN_ORDER else len(OPEN_ORDER)

    def cut(text: str, width: int) -> str:
        return text if len(text) <= width else text[:width - 1] + "…"

    open_rows = sorted([r for r in rows if head(r) != "DONE"], key=lambda r: (rank(r), r.age))
    done_rows = sorted([r for r in rows if head(r) == "DONE"], key=lambda r: r.age)
    shown = open_rows + (done_rows if show_done else [])
    return [("STATE", "TASK", "BRANCH", "REVIEW", "AGE")] + [
        (state_label(r),
         name(r) if markdown else cut(name(r), 50),
         r.branch if markdown else cut(r.branch, 32),
         r.verdict.upper() if r.verdict != "?" else "-",
         "today" if r.age == 0 else f"{r.age}d")
        for r in shown]


def table_lines(rows: list[TaskState], show_done: bool, markdown: bool,
                limit: int | None) -> list[str]:
    """The rendered table, bounded to `limit` data rows with a marker line when rows were dropped."""
    table = table_rows(rows, show_done, markdown)
    header, body = table[0], table[1:]
    shown, marker = rows_limit(body, limit)
    rendered: list[str] = []
    if markdown:
        for index, row in enumerate([header, *shown]):
            rendered.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
            if index == 0:
                rendered.append("|" + "|".join(["---"] * 5) + "|")
    else:
        widths = [max(len(row[i]) for row in [header, *shown]) for i in range(5)]
        for row in [header, *shown]:
            rendered.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    open_count = sum(1 for r in rows if head(r) != "DONE")
    done_rows = [r for r in rows if head(r) == "DONE"]
    unreviewed = sum(1 for r in done_rows if r.verdict.lower() not in ("pass", "warn"))
    rendered.append("")
    rendered.append(f"{len(rows)} tasks: {open_count} open, {len(done_rows)} done"
                    + ("" if show_done
                       else f" ({unreviewed} without a review pass; --all lists them)"))
    if marker:
        rendered.append(marker)
    return rendered


def json_row(r: TaskState) -> dict:
    """One task as machine-readable state: the fields an agent branches on, no display text."""
    return {"slug": name(r), "directory": str(r.task), "status": r.status or "",
            "state": head(r) or "", "branch": r.branch_name(""), "verdict": r.verdict,
            "age_days": r.age, "open": r.open, "done": r.done, "blocked": blocked_reason(r.task)}


def landed_section(landed: list[str]) -> list[str]:
    """The `landed: yes | no | unknown` lines (gathered by `ls_data.snapshot`, only with `--all`)."""
    if not landed:
        return []
    return ["", "landed (DONE means a PR was opened, not that it reached the default branch):", *landed]


def print_listing(rows: list[TaskState], args, landed=None) -> None:
    """The listing in whichever shape the flags select, bounded by `--limit` and `--max-chars`.

    `landed` replaces the `landed:` line reader (a `--watch` loop passes its cache).
    """
    if getattr(args, "json", False):
        records = [json_row(r) for r in rows]
        if args.all:
            kept = [(record, r) for record, r in list(zip(records, rows))[:args.limit] if head(r) == "DONE"]
            for (record, _), found in zip(kept, landed_rows([r.task for _, r in kept])):
                record.update(found)
        print(json_payload(records, args.limit, args.max_chars, what="tasks"))
        return
    if args.tsv:
        printed, marker = rows_limit(rows, args.limit)
        lines = ["\t".join([name(r), r.branch_name("?"), r.status or "?",
                            r.verdict, f"{r.age}d"]) for r in printed]
        if marker:
            lines.append(marker)
        print_lines(lines, args.max_chars, what="task rows", flag="--limit")
        return
    data = snapshot(rows, args.all, landed or landed_lines, args.limit)
    print_lines(table_lines(rows, args.all, args.md, args.limit) + data.blocked + landed_section(data.landed),
                args.max_chars, what="task table", flag="--max-chars")


def print_status_file(path: str) -> int:
    """The one reader for the `## Status` contract: hooks and tools must not re-implement it.

    A value outside the contract is still printed, so a hook can render a malformed task, but the
    command exits 2 and names the allowed set: a token no transition rule matches is a bug in
    whatever wrote it, and silence here is how `done` survived for 24 tasks.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    match = STATUS.search(text)
    value = match.group(2).strip() if match else ""
    print(value)
    try:
        token(value)
    except StatusError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


def apply_holds(decisions: list[tuple[TaskState, dict]], idle_days: int) -> int:
    """Write ON-HOLD for each idle spec; returns 1 when any write failed."""
    failed = []
    for r, rule in decisions:
        if rule["kind"] != "hold":
            continue
        fields = dict(idle_days=idle_days, prior=head(r), from_state=head(r))
        if not set_status(r, rule["status"].format(**fields), rule["log"].format(**fields)):
            failed.append(name(r))
    if failed:
        print(f'error: {len(failed)} spec(s) not updated: {", ".join(failed)}', file=sys.stderr)
        return 1
    return 0


def reconcile(rows: list[TaskState], apply: bool) -> int:
    """Report the four reconcile sections, and with `apply` write the idle holds."""
    rules = load_rules()
    decisions = [(r, rule) for r in rows if (rule := decide(r, rules))]
    of_kind = lambda kind: [r for r, rule in decisions if rule["kind"] == kind]
    unreviewed = [r for r in rows if head(r) == "DONE"
                  and r.verdict.lower() not in ("pass", "warn")]
    print("ready to open PR (all criteria checked, review pass or warn):")
    for r in of_kind("ready"):
        print(f"  {name(r)}\tstatus={r.status}\tchecked={r.done}")
    print(f"stalled IMPLEMENTING (>{rules['idle_days']}d, flagged only):")
    for r in of_kind("stalled"):
        print(f"  {name(r)}\t{r.age}d")
    print("done without review pass (flagged only):")
    for r in unreviewed:
        print(f"  {name(r)}\tverdict={r.verdict}")
    print(f"idle DRAFTING/APPROVED (>{rules['idle_days']}d -> ON-HOLD):")
    for r in of_kind("hold"):
        print(f"  {name(r)}\tstatus={r.status}\t{r.age}d")
    if apply:
        return apply_holds(decisions, rules["idle_days"])
    return 0
