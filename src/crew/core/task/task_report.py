"""Rendering task state for `crew-ls.py` (table, JSON, the landed section, the task cells) and `reconcile`.

Rendering never writes, so a listing failure is a display problem; `reconcile` applies holds and
statuses through `task_state` and records branch PRs through `task_progress`. The ISSUE, PR, PROGRESS,
ACTIVITY and TOKENS cells are shared by `crew ls --json` (one `lib.output.json_envelope` object) and the TUI.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crew.core.task.task_prs import Lookup

from crew.core.task.ls_data import STALE_DAYS, landed_lines, landed_rows, snapshot, stale
from crew.core.task.ls_report import stage_pairs
from crew.core.task.task_lock import LOCK_STALE_SECONDS, Lock, read_locks, worktree_paths
from crew.core.task.task_progress import Entry, append_pr, blocked_reason, count_text, read_entries, task_usage_totals
from crew.core.task.task_state import TaskState, closed_outside, decide, done_blockers, head, load_rules, name, set_status, tampered
from crew.core.task.task_status import STATUS, StatusError, token
from crew.lib.output import json_envelope, print_lines, rows_limit

OPEN_ORDER = ["IMPLEMENTING", "APPROVED", "DRAFTING", "ON-HOLD"]
CLOSED_OUTSIDE = "closed outside crew-task"  # the note of a `task_state.closed_outside` DONE task


def held_from(r: TaskState) -> str:
    """The state an ON-HOLD task was in (`was APPROVED` in its status), or ""."""
    was = re.search(r"was ([A-Za-z-]+)", r.status) if head(r) == "ON-HOLD" else None
    return was.group(1) if was else ""


def state_label(r: TaskState) -> str:
    """The STATE cell: `TAMPERED (spec says X, crew-task recorded Y)` first, else the state (an ON-HOLD's prior, a
    DONE task's `closed outside crew-task`)."""
    was = held_from(r)
    if closed_outside(r):
        return f"DONE ({CLOSED_OUTSIDE})"
    return tampered(r) or (f"ON-HOLD (was {was})" if was else head(r) or "?")


def ordered_rows(rows: list[TaskState], show_done: bool) -> list[TaskState]:
    """The listing order (`crew ls` and the TUI): open rows by state then idle days, then DONE rows when shown."""

    def rank(r: TaskState) -> int:
        return OPEN_ORDER.index(head(r)) if head(r) in OPEN_ORDER else len(OPEN_ORDER)

    open_rows = sorted([r for r in rows if head(r) != "DONE"], key=lambda r: (rank(r), r.activity))
    done_rows = sorted([r for r in rows if head(r) == "DONE"], key=lambda r: r.activity)
    return open_rows + (done_rows if show_done else [])


def age_cell(r: TaskState) -> str:
    """The AGE cell: `today`, or the days since the task last moved."""
    return "today" if r.activity == 0 else f"{r.activity}d"


def number_cell(url: str) -> str:
    """`#n` for an issue or PR URL, `-` for none."""
    return "#" + url.rstrip("/").rsplit("/", 1)[-1] if url else "-"


def pr_cell(r: TaskState) -> str:
    """`#n` for one PR, `N PRs` for several, `-` for none."""
    return number_cell(r.prs[-1] if r.prs else "") if len(r.prs) < 2 else f"{len(r.prs)} PRs"


def progress_cell(r: TaskState) -> str:
    """Checked over total checkboxes in the spec (the criteria `mark-done` counts), `-` for none."""
    return f"{r.done}/{r.done + r.open}" if r.done + r.open else "-"


def activity_cell(r: TaskState, entries: list[Entry], locks: list[Lock], now: float, live: bool = False) -> str:
    """`running <stage>` for an open stage or a live worker lock, `stuck <stage>` for a stage open past 6 h,
    else `idle Nd`; with an agent `live` (the TUI's transcripts), `running <stage>` or `running`, never stuck or idle.

    A stage is open from its `stage_start` until its `stage_end`; the lock is the one `crew implement`
    writes, live while younger than the guard's threshold. A DONE task is never running. `stuck` is not
    the 14-day `stale` of the listing and the JSON.
    """
    if head(r) != "DONE":
        _, open_starts = stage_pairs(entries)
        opened = sorted(((at.timestamp(), stage) for stage, (at, _) in open_starts.items()), reverse=True)
        fresh = [stage for at, stage in opened if now - at < LOCK_STALE_SECONDS]
        if fresh:
            return f"running {fresh[0]}"
        if any(lock.task == r.uuid and now - lock.started < LOCK_STALE_SECONDS for lock in locks):
            return "running implement"
        if opened or live:
            return f"{'running' if live else 'stuck'} {opened[0][1] if opened else ''}".rstrip()
    return f"idle {r.activity}d"


def tokens_cell(usage: dict) -> str:
    """The TOKENS cell of a `task_usage_totals` result: new tokens, `~` when approximate, `-` for none."""
    return count_text(usage["new"], usage["approximate"])


def task_cells(r: TaskState, entries: list[Entry], locks: list[Lock], now: float, usage: dict | None = None, live: bool = False) -> dict[str, str]:
    """The ISSUE, PR, PROGRESS, ACTIVITY and TOKENS cells of one task; `usage` is its `task_usage_totals` when the
    caller already has it, `live` whether an agent of it is running."""
    usage = task_usage_totals(entries) if usage is None else usage
    return {
        "ISSUE": number_cell(r.issue),
        "PR": pr_cell(r),
        "PROGRESS": progress_cell(r),
        "ACTIVITY": activity_cell(r, entries, locks, now, live),
        "TOKENS": tokens_cell(usage),
    }


def aligned(table: list[tuple[str, ...]]) -> list[str]:
    """Rows of cells as space-aligned text lines, each column as wide as its widest cell."""
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    return ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in table]


def cut(text: str, width: int) -> str:
    """`text` cut to `width` characters, its last one `…` when anything was dropped."""
    return text if len(text) <= width else text[: width - 1] + "…"


def fitted(table: list[tuple[str, ...]], width: int, order: tuple[str, ...] = ("NOTE", "TASK")) -> list[tuple[str, ...]]:
    """`table` (header first) with the `order` columns cut, first to last, until its `aligned` lines fit `width`;
    a column keeps at least its header's width, so a table that cannot fit stays as narrow as that allows."""
    header = table[0]
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    excess = sum(widths) + 2 * (len(widths) - 1) - width
    for column in order:
        if excess <= 0 or column not in header:
            continue
        index = header.index(column)
        keep = max(len(column), widths[index] - excess)
        excess -= widths[index] - keep
        widths[index] = keep
    return [header, *(tuple(cut(cell, widths[i]) for i, cell in enumerate(row)) for row in table[1:])]


def table_rows(rows: list[TaskState], show_done: bool, markdown: bool) -> list[tuple[str, ...]]:
    """The table header plus one row per displayed spec, longest-lived first within each state."""
    return [("STATE", "TASK", "REPO", "BRANCH", "REVIEW", "AGE")] + [
        (
            state_label(r),
            name(r) if markdown else cut(name(r), 50),
            r.repo or "-" if markdown else cut(r.repo or "-", 28),
            r.branch if markdown else cut(r.branch, 32),
            r.verdict.upper() if r.verdict != "?" else "-",
            age_cell(r),
        )
        for r in ordered_rows(rows, show_done)
    ]


def table_lines(rows: list[TaskState], show_done: bool, markdown: bool, limit: int | None, folded: list[TaskState] | None = None) -> list[str]:
    """The rendered table, bounded to `limit` data rows with a marker line when rows were dropped.

    `folded` rows (stale IMPLEMENTING) are counted in the footer and shown as one line, not as rows.
    """
    folded = folded or []
    table = table_rows([r for r in rows if r not in folded], show_done, markdown)
    header, body = table[0], table[1:]
    shown, marker = rows_limit(body, limit)
    rendered: list[str] = []
    if markdown:
        for index, row in enumerate([header, *shown]):
            rendered.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
            if index == 0:
                rendered.append("|" + "|".join(["---"] * len(header)) + "|")
    else:
        rendered.extend(aligned([header, *shown]))
    if folded:
        if markdown:
            rendered.append("")  # a Markdown table ends only at a blank line
        rendered.append(
            f"stale: {len(folded)} IMPLEMENTING with no activity for {STALE_DAYS}+ days (`--status implementing` lists them; `crew-task.py reconcile` reports them)"
        )
    open_count = sum(1 for r in rows if head(r) != "DONE")
    done_count = len(rows) - open_count
    rendered.append("")
    rendered.append(f"{len(rows)} tasks: {open_count} open, {done_count} done" + ("" if show_done or not done_count else " (--all lists them)"))
    if marker:
        rendered.append(marker)
    return rendered


def json_row(r: TaskState, locks: list[Lock], now: float) -> dict:
    """One task as machine-readable state: the fields an agent branches on, plus the ISSUE, PR, PROGRESS
    and ACTIVITY cells (`activity` is `running <stage>`, `stale` or `idle Nd`), and `tokens`
    (`task_usage_totals`: `new`, `cache_read`, each None when unrecorded, and `approximate`)."""
    entries = read_entries(r.task)
    return {
        "slug": name(r),
        "directory": str(r.task),
        "status": r.status or "",
        "state": head(r) or "",
        "tampered": tampered(r),
        "closed_outside": closed_outside(r),
        "repo": r.repo,
        "branch": r.branch_name(""),
        "verdict": r.verdict,
        "age_days": r.age,
        "activity_days": r.activity,
        "stale": stale(r),
        "open": r.open,
        "done": r.done,
        "blocked": blocked_reason(r.task),
        "issue": r.issue,
        "prs": list(r.prs),
        "progress": progress_cell(r),
        "activity": activity_cell(r, entries, locks, now),
        "tokens": task_usage_totals(entries),
    }


def landed_section(landed: list[str]) -> list[str]:
    """The `landed: yes | no | unknown` lines (gathered by `ls_data.snapshot`, only with `--all`)."""
    if not landed:
        return []
    return ["", "landed (DONE means a PR was opened, not that it reached the default branch):", *landed]


def print_listing(rows: list[TaskState], args, landed=None, scope: str = "") -> None:
    """The listing in whichever shape the flags select, bounded by `--limit` and `--max-chars`.

    `landed` replaces the `landed:` line reader (a `--watch` loop passes its cache); `scope` is the
    repository line printed under the table (never in `--json`).
    """
    if getattr(args, "json", False):
        locks, now = read_locks(worktree_paths()), time.time()
        records = [json_row(r, locks, now) for r in rows]
        if args.all:
            kept = [(record, r) for record, r in list(zip(records, rows))[: args.limit] if head(r) == "DONE"]
            for (record, _), found in zip(kept, landed_rows([r.task for _, r in kept])):
                record.update(found)
        print(json.dumps(json_envelope(records, args.limit, args.max_chars, what="tasks"), indent=2))
        return
    states = [state.upper() for state in getattr(args, "status", None) or []]
    show_done = args.all or "DONE" in states
    folded = [] if states else [r for r in rows if stale(r)]
    data = snapshot(rows, show_done, landed or landed_lines, args.limit)
    print_lines(
        table_lines(rows, show_done, args.md, args.limit, folded) + ([f"scope: {scope}"] if scope else []) + data.blocked + landed_section(data.landed),
        args.max_chars,
        what="task table",
        flag="--max-chars",
    )


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
        value = rule["status"].format(**fields)
        if set_status(r, value, rule["log"].format(**fields)):
            print(f"applied: {name(r)} -> {value.split()[0]}")
        else:
            failed.append(name(r))
    if failed:
        print(f"error: {len(failed)} spec(s) not updated: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


PrFinder = Callable[[list[TaskState]], "Lookup"]


def record_branch_prs(rows: list[TaskState], find: PrFinder, apply: bool) -> int:
    """Add the PRs `find` read for each task's branch to its PR list (written with `apply`); 1 on a failed write."""
    lookup, failed = find(rows), 0
    found = lookup.found
    if lookup.unchecked:
        print(f"{lookup.unchecked} task(s) not checked for a PR yet; the next reconcile asks again")
    for r in rows:
        for url in [url for url in found.get(r.task, []) if url not in r.prs]:
            try:
                if apply:
                    append_pr(r.task, url)
            except OSError as error:
                failed = 1
                print(f"error: {name(r)}: PR not recorded: {error}", file=sys.stderr)
                continue
            r.prs.append(url)
            print(f"{'recorded' if apply else 'would record'} PR: {name(r)} {url}")
    return failed


def reconcile(rows: list[TaskState], apply: bool, find: PrFinder | None = None) -> int:
    """Report the five reconcile sections (and the TAMPERED tasks, which no rule moves), and with `apply` write the
    idle holds and the branch PRs `find` reads.

    It never writes a status other than ON-HOLD: a task with an open PR is reported ready to mark done,
    and `crew-task.py mark-done` closes it.
    """
    rules = load_rules()
    failed = record_branch_prs(rows, find, apply) if find else 0
    decisions = [(r, rule) for r in rows if not tampered(r) and (rule := decide(r, rules))]
    of_kind = lambda kind: [r for r, rule in decisions if rule["kind"] == kind]
    print("ready to mark done (a PR is open, every criterion checked; crew-task.py mark-done closes it):")
    for r in of_kind("done"):
        print(f"  {name(r)}\tpr={r.prs[-1]}\tdir={r.task}")
    print("PR open, not closable (fix the reason, then crew-task.py mark-done):")
    for r in of_kind("pr-open"):
        print(f"  {name(r)}\tpr={r.prs[-1]}\t{'; '.join(done_blockers(r))}")
    print("ready to open PR (all criteria checked, review pass or warn, no PR recorded):")
    for r in of_kind("ready"):
        print(f"  {name(r)}\tstatus={r.status}\tchecked={r.done}")
    print(f"stalled IMPLEMENTING (>{rules['idle_days']}d, flagged only):")
    for r in of_kind("stalled"):
        print(f"  {name(r)}\t{r.age}d")
    print(f"idle DRAFTING/APPROVED (>{rules['idle_days']}d -> ON-HOLD):")
    for r in of_kind("hold"):
        print(f"  {name(r)}\tstatus={r.status}\t{r.age}d")
    altered = [r for r in rows if tampered(r)]
    if altered:
        print("tampered (no rule applies; crew-task.py restore-status <dir> [--accept <note>] clears it):")
    for r in altered:
        print(f"  {name(r)}\t{tampered(r)}\tdir={r.task}")
    if apply:
        return apply_holds(decisions, rules["idle_days"]) or failed
    return 0
