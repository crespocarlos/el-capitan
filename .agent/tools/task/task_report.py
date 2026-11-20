#!/usr/bin/env python3
"""Task listing and rendering: the table, the `--tsv` line, and the reconcile report.

Rendering is separate from `task_gates.py` because it never writes: a listing failure is a display
problem, while a gate failure must refuse. Both read the record `task_state.py` builds, so a change
to the record lands in one place.
"""
from __future__ import annotations

import sys
from pathlib import Path

from task_state import (
    STATUS,
    decide,
    head,
    load,
    load_rules,
    name,
    set_status,
)

OPEN_ORDER = ["IMPLEMENTING", "APPROVED", "DRAFTING", "ON-HOLD"]


def state_label(r: dict) -> str:
    if head(r) == "ON-HOLD":
        import re
        was = re.search(r"was ([A-Za-z-]+)", r["status"])
        return f"ON-HOLD (was {was.group(1)})" if was else "ON-HOLD"
    return head(r) or "?"


def table_rows(rows: list[dict], show_done: bool, markdown: bool) -> list[tuple[str, ...]]:
    """The table header plus one row per displayed spec, longest-lived first within each state."""
    def rank(r: dict) -> int:
        return OPEN_ORDER.index(head(r)) if head(r) in OPEN_ORDER else len(OPEN_ORDER)

    def cut(text: str, width: int) -> str:
        return text if len(text) <= width else text[:width - 1] + "…"

    open_rows = sorted([r for r in rows if head(r) != "DONE"], key=lambda r: (rank(r), r["age"]))
    done_rows = sorted([r for r in rows if head(r) == "DONE"], key=lambda r: r["age"])
    shown = open_rows + (done_rows if show_done else [])
    return [("STATE", "TASK", "BRANCH", "REVIEW", "AGE")] + [
        (state_label(r),
         name(r) if markdown else cut(name(r), 50),
         r["meta"].get("branch", "-") if markdown else cut(r["meta"].get("branch", "-"), 32),
         r["verdict"].upper() if r["verdict"] != "?" else "-",
         "today" if r["age"] == 0 else f"{r['age']}d")
        for r in shown]


def print_table(rows: list[dict], show_done: bool, markdown: bool = False) -> None:
    table = table_rows(rows, show_done, markdown)
    if markdown:
        for index, row in enumerate(table):
            print("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
            if index == 0:
                print("|" + "|".join(["---"] * 5) + "|")
    else:
        widths = [max(len(row[i]) for row in table) for i in range(5)]
        for row in table:
            print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    open_count = sum(1 for r in rows if head(r) != "DONE")
    done_rows = [r for r in rows if head(r) == "DONE"]
    unreviewed = sum(1 for r in done_rows if r["verdict"].lower() not in ("pass", "warn"))
    print()
    print(f"{len(rows)} tasks: {open_count} open, {len(done_rows)} done"
          + ("" if show_done else f" ({unreviewed} without a review pass; --all lists them)"))


def print_listing(rows: list[dict], args) -> None:
    if args.tsv:
        for r in rows:
            print("\t".join([name(r), r["meta"].get("branch", "?"), r["status"] or "?",
                             r["verdict"], f"{r['age']}d"]))
        return
    print_table(rows, args.all, args.md)


def load_rows(tasks_dir: Path) -> list[dict]:
    rows = []
    for task in sorted(tasks_dir.glob("*")):
        if not (task / "SPEC.md").exists():
            continue
        try:
            rows.append(load(task))
        except (OSError, ValueError, AttributeError) as error:
            print(f"warning: skipping {task.name}: {error}", file=sys.stderr)
    return rows


def print_status_file(path: str) -> int:
    """The one reader for the `## Status` contract: hooks and tools must not re-implement it."""
    try:
        text = Path(path).read_text()
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    match = STATUS.search(text)
    print(match.group(2).strip() if match else "")
    return 0


def apply_holds(decisions: list[tuple[dict, dict]], idle_days: int) -> int:
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


def reconcile(rows: list[dict], apply: bool) -> int:
    """Report the four reconcile sections, and with `apply` write the idle holds."""
    rules = load_rules()
    decisions = [(r, rule) for r in rows if (rule := decide(r, rules))]
    of_kind = lambda kind: [r for r, rule in decisions if rule["kind"] == kind]
    unreviewed = [r for r in rows if head(r) == "DONE"
                  and r["verdict"].lower() not in ("pass", "warn")]
    print("ready to open PR (all criteria checked, review pass or warn):")
    for r in of_kind("ready"):
        print(f"  {name(r)}\tstatus={r['status']}\tchecked={r['done']}")
    print(f"stalled IMPLEMENTING (>{rules['idle_days']}d, flagged only):")
    for r in of_kind("stalled"):
        print(f"  {name(r)}\t{r['age']}d")
    print("done without review pass (flagged only):")
    for r in unreviewed:
        print(f"  {name(r)}\tverdict={r['verdict']}")
    print(f"idle DRAFTING/APPROVED (>{rules['idle_days']}d -> ON-HOLD):")
    for r in of_kind("hold"):
        print(f"  {name(r)}\tstatus={r['status']}\t{r['age']}d")
    if apply:
        return apply_holds(decisions, rules["idle_days"])
    return 0
