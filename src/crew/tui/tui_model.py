"""The crew TUI's view model: the tasks, workers and report views as plain rows, with no terminal.

`collect` reads the task directory, the worker locks, the report (`ls_data`/`ls_report`) and running agents'
transcripts (`task_live`); `build` turns that into views; `render` prints a view as text (`--once`); `moves` lists
the `crew-task.py` calls a task's state allows. Nothing here writes, runs a command, calls a model or reads
GitHub, except `landed_for`, which the front end calls on a key.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crew.task.ls_data import landed_rows, load_rows, repo_filter, select, stale
from crew.task.ls_report import cursor_sessions, stage_pairs
from crew.task.ls_report import gather as gather_report
from crew.task.ls_report import render as render_report
from crew.task.task_cost import session_text
from crew.task.task_gates import CLOSABLE
from crew.task.task_live import Live, Seen, ended_at, running_agents
from crew.task.task_lock import LOCK_STALE_SECONDS, Lock, read_locks, worktree_paths
from crew.task.task_progress import blocked_reason, count_text, read_entries, sum_usage, task_usage_totals, usage_text
from crew.task.task_report import CLOSED_OUTSIDE, aligned, fitted, held_from, ordered_rows, task_cells
from crew.task.task_state import TaskState, closed_outside, head, name, spec_branch, tampered
from crew.task.task_status import StatusError, token

VIEWS = ("tasks", "workers", "report")
STAGE_STALE_SECONDS = LOCK_STALE_SECONDS  # a stage open this long outlived any worker the guard still protects
NOT_READ = "?"  # a DONE task's `landed` before the GitHub key is pressed
LINKED = ("ISSUE", "PR")  # the cells that are terminal links in the app; `o` and `O` open them
CREW_TASK = (sys.executable, "-m", "crew.task.crew_task")  # what ~/.agent/bin/crew-task.py runs
# The default `--pr-url` note of the close move (`mark-done --force`): shipped work for IMPLEMENTING, else stale.
SHIPPED_NOTE, STALE_NOTE = "none (committed to main)", "closed: stale"
# The gates of `crew-task.py` and the one state each moves from (`task_gates.py`); the CLI refuses any other.
GATES = (("mark-approved", "DRAFTING", "approve"), ("mark-implementing", "APPROVED", "start"), ("mark-done", "IMPLEMENTING", "mark done"))


@dataclass(frozen=True)
class Filters:
    """What `crew ls` filters on: `repo` (None: `ls.repo` of config.json; `here`; `all`), states, done rows."""

    repo: str | None = None
    states: tuple[str, ...] = ()
    done: bool = False
    days: int = 30


@dataclass
class View:
    """One screen: a title, a table header and rows of plain cells, note lines under the table, and per row
    the URL behind each linked cell (`{"ISSUE": url, "PR": url}`, only the ones the task has)."""

    title: str
    header: tuple[str, ...]
    rows: list[tuple[str, ...]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    moves: list[list[Move]] = field(default_factory=list)


@dataclass(frozen=True)
class Move:
    """One `crew-task.py` call the app's `s` key offers: a label, the arguments after the script and, for a
    call that takes free text, its prompt (`ask`) and default; the text is the last argument."""

    label: str
    args: tuple[str, ...]
    ask: str = ""
    default: str = ""

    def argv(self, text: str = "") -> list[str]:
        return [*CREW_TASK, *self.args, *([text] if self.ask else [])]


def moves(state: str, task: Path, prs: list[str], branch: str = "") -> list[Move]:
    """The calls `crew-task.py` accepts from `state`: its gate (start on the spec's `## Branch:`, none without one;
    mark done with the newest PR from IMPLEMENTING), then `blocked` with a reason for any task not DONE, and close as
    done (`mark-done --force` with a note) for a state the CLI closes (`CLOSABLE`: not ABANDONED), except an
    IMPLEMENTING task with a PR. The CLI still checks every gate."""
    found = []
    for command, source, label in GATES:
        if state != source:
            continue
        if command == "mark-implementing":
            if branch:
                found.append(Move(f"{label} on {branch} ({command})", (command, str(task), "--branch", branch)))
        elif command != "mark-done":
            found.append(Move(f"{label} ({command})", (command, str(task))))
        elif prs:
            found.append(Move(f"{label} with PR {prs[-1]} ({command})", (command, str(task), "--pr-url", prs[-1])))
    if state != "DONE":
        found.append(Move("blocked with a reason (blocked)", ("blocked", str(task)), ask="reason"))
    if state in CLOSABLE and not (state == "IMPLEMENTING" and prs):
        found.append(
            Move(
                "close as done (mark-done --force)",
                ("mark-done", str(task), "--force", "--pr-url"),
                ask="note",
                default=SHIPPED_NOTE if state == "IMPLEMENTING" else STALE_NOTE,
            )
        )
    return found


def restore_moves(task: Path) -> list[Move]:
    """The only calls a TAMPERED task takes (every gate refuses it): write the recorded status back, or keep the
    spec's with a note."""
    return [
        Move("restore the recorded status (restore-status)", ("restore-status", str(task))),
        Move("keep the spec's status (restore-status --accept)", ("restore-status", str(task), "--accept"), ask="note"),
    ]


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


@dataclass(frozen=True)
class Snapshot:
    """What both the tasks and the workers view read: each task's PROGRESS entries, the worker locks, the moment, and
    the running agents per task (`task_live`)."""

    entries: dict[Path, list]
    locks: list[Lock]
    now: float
    live: dict[Path, list[Live]] = field(default_factory=dict)


def tasks_view(rows: list[TaskState], show_done: bool, landed: dict[str, str], scope: str, seen: Snapshot) -> View:
    """STATE, TASK, REPO, ISSUE, PR, PROGRESS, ACTIVITY, TOKENS (`task_report.task_cells`), LANDED and a NOTE (`was
    <state>` of an ON-HOLD task, the BLOCKED reason, or `stale` past 14 idle days) per task, in `crew ls` order, then
    the tokens of the rows shown. REPO drops the owner every shown row shares, so TASK keeps the width.
    Live agents add their tokens to ACTIVITY only: TOKENS and the total are what the task recorded."""
    view = View("tasks", ("STATE", "TASK", "REPO", "ISSUE", "PR", "PROGRESS", "ACTIVITY", "TOKENS", "LANDED", "NOTE"))
    shown = ordered_rows(rows, show_done)
    owners = {r.repo.split("/", 1)[0] for r in shown if "/" in r.repo}
    shared = len(owners) == 1 and all("/" in r.repo for r in shown if r.repo)
    totals, unstarted = [], []
    for r in shown:
        reason, held = blocked_reason(r.task), held_from(r)
        note = "; ".join(
            filter(
                None,
                [f"was {held}" if held else "", CLOSED_OUTSIDE if closed_outside(r) else "", f"BLOCKED: {reason}" if reason else ("stale" if stale(r) else "")],
            )
        )
        done = head(r) == "DONE"
        repo = (r.repo.split("/", 1)[1] if shared and "/" in r.repo else r.repo) or "-"
        entries = seen.entries.get(r.task, [])
        totals.append(task_usage_totals(entries))
        cells = task_cells(r, entries, seen.locks, seen.now, [agent.new for agent in seen.live.get(r.task, [])], totals[-1])
        altered = tampered(r)
        view.rows.append(
            (altered or head(r) or "?", name(r), repo, *(cells[key] for key in view.header[3:8]), landed.get(str(r.task), NOT_READ) if done else "-", note)
        )
        view.links.append({key: url for key, url in (("ISSUE", r.issue), ("PR", r.prs[-1] if r.prs else "")) if url})
        branch = spec_branch(r.text)
        view.moves.append(restore_moves(r.task) if altered else moves(head(r), r.task, r.prs, branch))
        if head(r) == "APPROVED" and not branch:
            unstarted.append(name(r))
    open_count = sum(1 for r in rows if head(r) != "DONE")
    view.notes.append(f"{len(rows)} tasks: {open_count} open, {len(rows) - open_count} done; scope: {scope}")
    view.notes.append(f"tokens: {usage_text(sum_usage(totals))} across {len(shown)} tasks shown")
    sessions = cursor_sessions({r.task: seen.entries.get(r.task, []) for r in shown}, None)
    if sessions:
        view.notes.append(f"{session_text(sessions)} across the tasks shown, apart from TOKENS")
    if show_done and any(head(r) == "DONE" and str(r.task) not in landed for r in rows):
        view.notes.append(f"LANDED {NOT_READ}: not read yet; the GitHub key reads each DONE task's PR")
    if unstarted:
        view.notes.append(
            f"no start move for {', '.join(unstarted)}: SPEC.md names no `## Branch:`; start it from its checkout with crew-task.py mark-implementing <TASK_DIR>"
        )
    return view


def open_stages(rows: list[TaskState], entries: dict[Path, list]) -> list[tuple[str, str, datetime, str]]:
    """`(task, stage, started, detail)` for every `stage_start` with no later `stage_end` (`ls_report.stage_pairs`)."""
    found = []
    for r in rows:
        if head(r) == "DONE":
            continue
        _, running = stage_pairs(entries.get(r.task, []))
        found.extend((name(r), stage, at, " ".join(f"{k}={v}" for k, v in given.items() if k != "stage")) for stage, (at, given) in running.items())
    return found


def workers_view(rows: list[TaskState], seen: Snapshot) -> View:
    """Running stages (from PROGRESS) and worker locks, each with its age (past 6 h either is stale), then each
    running agent (`task_live`) with the time since its transcript last moved and its tokens so far."""
    view = View("workers", ("KIND", "TASK", "WHAT", "AGE", "NOTE"))
    entries, locks, now, live = seen.entries, seen.locks, seen.now, seen.live
    for task, stage, at, detail in open_stages(rows, entries):
        age = now - at.timestamp()
        note = "; ".join(filter(None, [detail, "stale: no stage_end" if age >= STAGE_STALE_SECONDS else ""]))
        view.rows.append(("stage", task, stage, ago(age), note))
    slugs = {r.uuid: name(r) for r in rows}
    for lock in sorted(locks, key=lambda lock: lock.started):
        age = now - lock.started
        view.rows.append(
            ("lock", slugs.get(lock.task, lock.task), str(lock.tree), ago(age), "stale: the guard ignores it" if age >= LOCK_STALE_SECONDS else "live")
        )
    tasks = {r.task: name(r) for r in rows}
    for agent in sorted((agent for agents in live.values() for agent in agents), key=lambda a: a.modified):
        used = f"new {count_text(agent.new)}, cache reads {count_text(agent.cache_read)}"
        view.rows.append(("agent", tasks.get(agent.task, str(agent.task)), f"agent-{agent.agent_id}", ago(now - agent.modified), used))
    if not view.rows:
        view.notes.append("no stage, worker lock or agent running in this repository's worktrees")
    return view


def report_view(report: dict, scope: str) -> View:
    """`crew report` as one line per row."""
    return View("report", ("REPORT",), [(line,) for line in render_report(report, scope)])


def build(
    rows: list[TaskState],
    filters: Filters,
    scope: str,
    *,
    entries: dict[Path, list],
    locks: list[Lock],
    report: dict,
    landed: dict[str, str] | None = None,
    now: float | None = None,
    live: dict[Path, list[Live]] | None = None,
) -> dict[str, View]:
    """Every view from data already read; pure."""
    show_done = filters.done or "DONE" in filters.states
    seen = Snapshot(entries, locks, time.time() if now is None else now, live or {})
    return {"tasks": tasks_view(rows, show_done, landed or {}, scope, seen), "workers": workers_view(rows, seen), "report": report_view(report, scope)}


def config_dirs(home: Path | None = None) -> list[Path]:
    """The Claude config dirs whose transcripts hold running agents: `~/.claude`, `$CLAUDE_CONFIG_DIR`, and the
    `config_dirs` of `~/.agent/install-manifest.json` (read as JSON; an unreadable manifest adds none). Each real
    directory once, as `memory_claude.default_config_dirs` counts them."""
    home = Path.home() if home is None else home
    named = os.environ.get("CLAUDE_CONFIG_DIR", "")
    try:
        manifest = json.loads((home / ".agent" / "install-manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    recorded = manifest.get("config_dirs", []) if isinstance(manifest, dict) else []
    found: dict[str, Path] = {}
    for directory in [home / ".claude", *([named] if named else []), *(i for i in recorded if isinstance(i, str))]:
        path = Path(directory).expanduser()
        found.setdefault(os.path.realpath(path), path)
    return list(found.values())


def scope_of(repos: set[str] | None) -> str:
    return "repo " + ", ".join(sorted(repos)) if repos else "every repo"


def load(tasks_dir: Path, filters: Filters, here: Callable[[], dict[str, str]] | None = None) -> tuple[list[TaskState], str]:
    """The filtered rows and their scope line, as `crew ls` selects them."""
    repos = repo_filter(filters.repo) if here is None else repo_filter(filters.repo, here)
    return select(load_rows(tasks_dir), repos, list(filters.states)), scope_of(repos)


def collect(
    tasks_dir: Path,
    filters: Filters,
    landed: dict[str, str] | None = None,
    trees: list[Path] | None = None,
    here: Callable[[], dict[str, str]] | None = None,
    now: float | None = None,
    claude_dirs: list[Path] | None = None,
    live_cache: dict[str, Seen] | None = None,
) -> dict[str, View]:
    """Read everything the views show (files, `git worktree list`, and the running agents' transcripts in
    `claude_dirs`, default `config_dirs()`), then `build`. `live_cache` is the front end's per-file cache."""
    rows, scope = load(tasks_dir, filters, here)
    moment = time.time() if now is None else now
    report = gather_report(rows, filters.days, now=datetime.fromtimestamp(moment, UTC))
    entries = {r.task: read_entries(r.task) for r in rows}
    running = [r.task for r in rows if head(r) != "DONE"]
    ended = {agent: at for task in running for agent, at in ended_at(entries[task]).items()}
    live = running_agents(running, config_dirs() if claude_dirs is None else claude_dirs, ended, moment, live_cache)
    return build(
        rows,
        filters,
        scope,
        entries=entries,
        locks=read_locks(worktree_paths() if trees is None else trees),
        report=report,
        landed=landed,
        now=moment,
        live=live,
    )


def landed_for(tasks_dir: Path, filters: Filters, reader: Callable | None = None) -> dict[str, str]:
    """`{task dir: yes|no|unknown|closed}` for the DONE rows shown: the one GitHub read, behind an explicit key."""
    rows, _ = load(tasks_dir, filters)
    done = [r.task for r in rows if head(r) == "DONE"]
    found = landed_rows(done) if reader is None else landed_rows(done, reader)
    return {str(task): row["landed"] for task, row in zip(done, found)}


def render(view: View, width: int = 0) -> list[str]:
    """A view as aligned plain text: the title, the table (cut to `width` columns, NOTE first and then TASK, when
    `width` is set), the notes."""
    table = [view.header, *view.rows]
    return [f"== {view.title} ==", *aligned(fitted(table, width) if width > 0 else table), *view.notes]
