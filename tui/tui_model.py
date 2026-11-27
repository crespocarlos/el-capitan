"""The crew TUI's view model: the tasks, workers and report views as plain rows, with no terminal.

`collect` reads the task directory, the worker locks and the report through `ls_data`/`ls_report`;
`build` turns what was read into views; `render` prints a view as text (`--once`). Nothing here
writes, calls a model or reads GitHub, except `landed_for`, which the front end calls on a key.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import tui_bootstrap  # noqa: F401

from ls_data import landed_rows, load_rows, repo_filter, select, stale
from ls_report import gather as gather_report
from ls_report import render as render_report
from ls_report import stage_pairs
from task_lock import LOCK_NAME
from task_progress import blocked_reason, read_entries
from task_report import age_cell, aligned, ordered_rows, state_label
from task_state import TaskState, head, name
from task_status import StatusError, token

from lib.git import GitError

VIEWS = ("tasks", "workers", "report")
LOCK_STALE_SECONDS = 21600  # `STALE_SECONDS` of .claude/hooks/guard/worker-tree.sh: an older lock does not guard
STAGE_STALE_SECONDS = LOCK_STALE_SECONDS  # a stage open this long outlived any worker the guard still protects
NOT_READ = "?"  # a DONE task's `landed` before the GitHub key is pressed


@dataclass(frozen=True)
class Filters:
    """What `crew ls` filters on: `repo` (None: the repository around the cwd; `all`), states, done rows."""

    repo: str | None = None
    states: tuple[str, ...] = ()
    done: bool = False
    days: int = 30


@dataclass
class View:
    """One screen: a title, a table header and rows of cells, and note lines under the table."""

    title: str
    header: tuple[str, ...]
    rows: list[tuple[str, ...]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Lock:
    """A `.crew-worker.lock`: the tree it guards, its task, and its start (POSIX seconds)."""

    tree: Path
    task: str
    started: float


def parse_filter(text: str, base: Filters | None = None) -> Filters:
    """`repo:R status:S [status:T] done` applied over `base` (the current filter).

    The text replaces the states; repo, done and days stay as `base` has them unless the text sets
    them. An unknown word or status raises ValueError.
    """
    base = base or Filters()
    repo, states, done = base.repo, [], base.done
    for word in text.split():
        key, _, value = word.partition(":")
        if key == "repo" and value:
            repo = value
        elif key == "status" and value:
            try:
                states.append(token(value) or value.upper())
            except StatusError as error:
                raise ValueError(str(error)) from error
        elif word in ("done", "all"):
            done = True
        else:
            raise ValueError(f"unknown filter {word!r}: use repo:OWNER/NAME, status:STATE, done")
    return Filters(repo=repo, states=tuple(states), done=done, days=base.days)


def ago(seconds: float) -> str:
    """A duration as `5m`, `3h` or `2d`."""
    minutes = max(0, int(seconds // 60))
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h" if minutes < 24 * 60 else f"{minutes // (24 * 60)}d"


def tasks_view(rows: list[TaskState], show_done: bool, landed: dict[str, str], scope: str) -> View:
    """STATE, TASK, REPO, AGE, LANDED and a NOTE (the BLOCKED reason, or `stale`) per task, in `crew ls` order."""
    view = View("tasks", ("STATE", "TASK", "REPO", "AGE", "LANDED", "NOTE"))
    for r in ordered_rows(rows, show_done):
        reason = blocked_reason(r.task)
        note = f"BLOCKED: {reason}" if reason else ("stale" if stale(r) else "")
        done = head(r) == "DONE"
        view.rows.append((state_label(r), name(r), r.repo or "-", age_cell(r),
                          landed.get(str(r.task), NOT_READ) if done else "-", note))
    open_count = sum(1 for r in rows if head(r) != "DONE")
    view.notes.append(f"{len(rows)} tasks: {open_count} open, {len(rows) - open_count} done; scope: {scope}")
    if show_done and any(head(r) == "DONE" and str(r.task) not in landed for r in rows):
        view.notes.append(f"LANDED {NOT_READ}: not read yet; the GitHub key reads each DONE task's PR")
    return view


def open_stages(rows: list[TaskState], entries: dict[Path, list]) -> list[tuple[str, str, datetime, str]]:
    """`(task, stage, started, detail)` for every `stage_start` with no later `stage_end` (`ls_report.stage_pairs`)."""
    found = []
    for r in rows:
        if head(r) == "DONE":
            continue
        _, running = stage_pairs(entries.get(r.task, []))
        found.extend((name(r), stage, at, " ".join(f"{k}={v}" for k, v in given.items() if k != "stage"))
                     for stage, (at, given) in running.items())
    return found


def workers_view(rows: list[TaskState], entries: dict[Path, list], locks: list[Lock], now: float) -> View:
    """Running stages (from PROGRESS) and worker locks, each with its age; past 6 h either is stale."""
    view = View("workers", ("KIND", "TASK", "WHAT", "AGE", "NOTE"))
    for task, stage, at, detail in open_stages(rows, entries):
        age = now - at.timestamp()
        note = "; ".join(filter(None, [detail, "stale: no stage_end" if age >= STAGE_STALE_SECONDS else ""]))
        view.rows.append(("stage", task, stage, ago(age), note))
    slugs = {r.uuid: name(r) for r in rows}
    for lock in sorted(locks, key=lambda lock: lock.started):
        age = now - lock.started
        view.rows.append(("lock", slugs.get(lock.task, lock.task), str(lock.tree), ago(age),
                          "stale: the guard ignores it" if age >= LOCK_STALE_SECONDS else "live"))
    if not view.rows:
        view.notes.append("no stage running and no worker lock in this repository's worktrees")
    return view


def report_view(report: dict, scope: str) -> View:
    """`crew report` as one line per row."""
    return View("report", ("REPORT",), [(line,) for line in render_report(report, scope)])


def build(rows: list[TaskState], filters: Filters, scope: str, *, entries: dict[Path, list], locks: list[Lock],
          report: dict, landed: dict[str, str] | None = None, now: float | None = None) -> dict[str, View]:
    """Every view from data already read; pure."""
    show_done = filters.done or "DONE" in filters.states
    moment = time.time() if now is None else now
    return {"tasks": tasks_view(rows, show_done, landed or {}, scope),
            "workers": workers_view(rows, entries, locks, moment),
            "report": report_view(report, scope)}


def parse_lock(tree: Path, text: str) -> Lock | None:
    """The lock `task_lock.write_lock` wrote, or None when it has no task or no integer start."""
    values = dict(line.partition("=")[::2] for line in text.splitlines() if "=" in line)
    started = values.get("started", "")
    if not values.get("task") or not started.isdigit():
        return None
    return Lock(tree, values["task"], float(started))


def worktree_paths() -> list[Path]:
    """The worktrees of the repository around the cwd; none outside a repository."""
    from task_worktrees import worktrees

    try:
        return [path for path, _ in worktrees()]
    except (GitError, OSError):
        return []


def read_locks(trees: list[Path]) -> list[Lock]:
    found = []
    for tree in trees:
        try:
            lock = parse_lock(tree, (tree / LOCK_NAME).read_text(encoding="utf-8"))
        except OSError:
            continue
        found.extend([lock] if lock else [])
    return found


def scope_of(repos: set[str] | None) -> str:
    return "repo " + ", ".join(sorted(repos)) if repos else "every repo"


def load(tasks_dir: Path, filters: Filters, here: Callable[[], dict[str, str]] | None = None
         ) -> tuple[list[TaskState], str]:
    """The filtered rows and their scope line, as `crew ls` selects them."""
    repos = repo_filter(filters.repo) if here is None else repo_filter(filters.repo, here)
    return select(load_rows(tasks_dir), repos, list(filters.states)), scope_of(repos)


def collect(tasks_dir: Path, filters: Filters, landed: dict[str, str] | None = None, trees: list[Path] | None = None,
            here: Callable[[], dict[str, str]] | None = None, now: float | None = None) -> dict[str, View]:
    """Read everything the views show (files and `git worktree list` only), then `build`."""
    rows, scope = load(tasks_dir, filters, here)
    moment = time.time() if now is None else now
    report = gather_report(rows, filters.days, now=datetime.fromtimestamp(moment, timezone.utc))
    return build(rows, filters, scope, entries={r.task: read_entries(r.task) for r in rows},
                 locks=read_locks(worktree_paths() if trees is None else trees), report=report,
                 landed=landed, now=moment)


def landed_for(tasks_dir: Path, filters: Filters, reader: Callable | None = None) -> dict[str, str]:
    """`{task dir: yes|no|unknown}` for the DONE rows shown: the one GitHub read, behind an explicit key."""
    rows, _ = load(tasks_dir, filters)
    done = [r.task for r in rows if head(r) == "DONE"]
    found = landed_rows(done) if reader is None else landed_rows(done, reader)
    return {str(task): row["landed"] for task, row in zip(done, found)}


def render(view: View) -> list[str]:
    """A view as aligned plain text: the title, the table, the notes."""
    return [f"== {view.title} ==", *aligned([view.header, *view.rows]), *view.notes]
