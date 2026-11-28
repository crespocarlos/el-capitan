"""The crew TUI's view model: the tasks, workers and report views as plain rows, with no terminal.

`collect` reads tasks, each task repository's worker locks, the report and agents' transcripts; `build` makes views
whose rows are keyed by task or worker; `live_tick` reads only new transcript lines, for LIVE; `render` prints a view
(`--once`); `moves` lists the `crew-task.py` calls a state allows, and why others are unavailable. Nothing here writes,
runs a command, calls a model or reads GitHub, except `landed_for`, which the front end calls on a key.
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
from crew.task.task_live import Live, Seen, ended_at, running_agents, session_agents
from crew.task.task_lock import LOCK_STALE_SECONDS, Lock, read_locks, worktree_paths
from crew.task.task_progress import blocked_reason, count_text, read_entries, sum_usage, task_usage_totals, usage_text
from crew.task.task_report import CLOSED_OUTSIDE, aligned, fitted, held_from, number_cell, ordered_rows, task_cells
from crew.task.task_state import TaskState, closed_outside, head, name, recorded_state, spec_branch, tampered
from crew.task.task_status import StatusError, token

VIEWS = ("tasks", "workers", "report")
STAGE_STALE_SECONDS = LOCK_STALE_SECONDS  # a stage open this long outlived any worker the guard still protects
NOT_READ = "?"  # a DONE task's `landed` before the GitHub key is pressed
LINKED = ("ISSUE", "PR")  # the cells that are terminal links in the app; `o` and `O` open them
CREW_TASK = (sys.executable, "-m", "crew.task.crew_task")  # what ~/.agent/bin/crew-task.py runs
# The default `--pr-url` note of the close move (`mark-done --force`): shipped work for IMPLEMENTING, else stale.
SHIPPED_NOTE, STALE_NOTE = "none (committed to main)", "closed: stale"


@dataclass(frozen=True)
class Filters:
    """What `crew ls` filters on: `repo` (None: `ls.repo` of config.json; `here`; `all`), states, done rows."""

    repo: str | None = None
    states: tuple[str, ...] = ()
    done: bool = False
    days: int = 30


@dataclass
class View:
    """One screen: a title, a table header and rows of plain cells, note lines under the table, and per row its key
    (the task dir, or the worker), the URL behind each linked cell (`{"ISSUE": url, "PR": url}`) and its moves."""

    title: str
    header: tuple[str, ...]
    rows: list[tuple[str, ...]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    moves: list[list[Move]] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Move:
    """One `crew-task.py` call the status dialog offers: `key` picks it, the task goes from `source` to `target`; a call
    that takes free text has its prompt (`ask`) and default, the text last. With `why` it is unavailable, and says why."""

    key: str
    label: str
    source: str
    target: str
    args: tuple[str, ...] = ()
    ask: str = ""
    default: str = ""
    why: str = ""

    def title(self) -> str:
        return f"{self.source} → {self.target} [{self.key}] {self.label}" + (f" (unavailable: {self.why})" if self.why else "")

    def argv(self, text: str = "") -> list[str]:
        return [*CREW_TASK, *self.args, *([text] if self.ask else [])]


def moves(state: str, task: Path, prs: list[str], branch: str = "") -> list[Move]:
    """The calls `crew-task.py` accepts from `state`: its gate (start on the spec's `## Branch:`, mark done with the newest
    PR), then `blocked` with a reason for any task not DONE, and close as done (`mark-done --force` with a note) for a
    state the CLI closes (`CLOSABLE`), except an IMPLEMENTING task with a PR. A gate the task cannot pass yet, and close
    for a state the CLI does not close, come back unavailable with the reason. The CLI still checks every gate."""
    t = str(task)
    found = []
    if state == "DRAFTING":
        found.append(Move("a", "Approve", state, "APPROVED", ("mark-approved", t)))
    elif state == "APPROVED":
        why = "" if branch else "SPEC.md names no `## Branch:`; run crew-task.py mark-implementing <TASK_DIR> from its checkout"
        found.append(Move("i", f"Start on {branch}" if branch else "Start", state, "IMPLEMENTING", ("mark-implementing", t, "--branch", branch), why=why))
    elif state == "IMPLEMENTING":
        pr = prs[-1] if prs else ""
        found.append(
            Move(
                "d",
                f"Mark done with PR {number_cell(pr)}" if pr else "Mark done with its PR",
                state,
                "DONE",
                ("mark-done", t, "--pr-url", pr),
                why="" if pr else "no PR recorded",
            )
        )
    if state == "DONE":
        return found
    found.append(Move("b", "Block, with a reason", state, "BLOCKED", ("blocked", t), ask="reason"))
    if not (state == "IMPLEMENTING" and prs):
        note = SHIPPED_NOTE if state == "IMPLEMENTING" else STALE_NOTE
        why = "" if state in CLOSABLE else f"crew-task.py does not close {state or 'an unset status'}"
        found.append(Move("c", "Close as done (--force), with a note", state, "DONE", ("mark-done", t, "--force", "--pr-url"), "note", note, why))
    return found


def restore_moves(r: TaskState) -> list[Move]:
    """The only calls a TAMPERED task takes (every gate refuses it): write the recorded status back, or keep the
    spec's with a note."""
    t = str(r.task)
    return [
        Move("r", "Restore the recorded status", "TAMPERED", recorded_state(r), ("restore-status", t)),
        Move("k", "Keep the spec's status (--accept), with a note", "TAMPERED", head(r) or "?", ("restore-status", t, "--accept"), ask="note"),
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


def live_text(agents: list[Live]) -> str:
    """The LIVE cell: the running agents' new tokens so far, `92k`, or `2 · 180k` for two; `-` for none."""
    total = count_text(sum(agent.new for agent in agents))
    return "-" if not agents else total if len(agents) == 1 else f"{len(agents)} · {total}"


@dataclass(frozen=True)
class Snapshot:
    """What both the tasks and the workers view read: each task's PROGRESS entries, the worker locks, the moment, and
    the running agents per task (`task_live`)."""

    entries: dict[Path, list]
    locks: list[Lock]
    now: float
    live: dict[Path, list[Live]] = field(default_factory=dict)


def tasks_view(rows: list[TaskState], show_done: bool, landed: dict[str, str], scope: str, seen: Snapshot) -> View:
    """STATE, TASK, REPO, ISSUE, PR, PROGRESS, ACTIVITY, LIVE (the running agents' tokens, apart from TOKENS and the
    total), TOKENS (`task_report.task_cells`), LANDED and a NOTE (`was <state>` of an ON-HOLD task, the BLOCKED reason,
    or `stale` past 14 idle days) per task, in `crew ls` order, then the tokens of the rows shown. REPO drops the owner
    every shown row shares, so TASK keeps the width."""
    view = View("tasks", ("STATE", "TASK", "REPO", "ISSUE", "PR", "PROGRESS", "ACTIVITY", "LIVE", "TOKENS", "LANDED", "NOTE"))
    shown = ordered_rows(rows, show_done)
    owners = {r.repo.split("/", 1)[0] for r in shown if "/" in r.repo}
    shared = len(owners) == 1 and all("/" in r.repo for r in shown if r.repo)
    totals = []
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
        cells = task_cells(r, entries, seen.locks, seen.now, totals[-1], bool(seen.live.get(r.task)))
        cells["LIVE"] = live_text(seen.live.get(r.task, []))
        altered = tampered(r)
        view.rows.append(
            (altered or head(r) or "?", name(r), repo, *(cells[key] for key in view.header[3:9]), landed.get(str(r.task), NOT_READ) if done else "-", note)
        )
        view.keys.append(str(r.task))
        view.links.append({key: url for key, url in (("ISSUE", r.issue), ("PR", r.prs[-1] if r.prs else "")) if url})
        view.moves.append(restore_moves(r) if altered else moves(head(r), r.task, r.prs, spec_branch(r.text)))
    open_count = sum(1 for r in rows if head(r) != "DONE")
    view.notes.append(f"{len(rows)} tasks: {open_count} open, {len(rows) - open_count} done; scope: {scope}")
    view.notes.append(f"tokens: {usage_text(sum_usage(totals))} across {len(shown)} tasks shown")
    sessions = cursor_sessions({r.task: seen.entries.get(r.task, []) for r in shown}, None)
    if sessions:
        view.notes.append(f"{session_text(sessions)} across the tasks shown, apart from TOKENS")
    if show_done and any(head(r) == "DONE" and str(r.task) not in landed for r in rows):
        view.notes.append(f"LANDED {NOT_READ}: not read yet; the GitHub key reads each DONE task's PR")
    return view


def workers_view(rows: list[TaskState], seen: Snapshot) -> View:
    """Running stages (from PROGRESS) and worker locks, each with its age (past 6 h either is stale), then each
    running agent (`task_live`) with the time since its transcript last moved and its tokens so far."""
    view = View("workers", ("KIND", "TASK", "WHAT", "AGE", "NOTE"))
    entries, locks, now, live = seen.entries, seen.locks, seen.now, seen.live

    def add(key: str, *row: str) -> None:
        view.keys.append(key)
        view.rows.append(row)

    for r in (r for r in rows if head(r) != "DONE"):
        for stage, (at, given) in stage_pairs(entries.get(r.task, []))[1].items():
            age = now - at.timestamp()
            detail = " ".join(f"{k}={v}" for k, v in given.items() if k not in ("stage", "session"))
            add(
                f"stage {r.task} {stage}",
                "stage",
                name(r),
                stage,
                ago(age),
                "; ".join(filter(None, [detail, "stale: no stage_end" if age >= STAGE_STALE_SECONDS else ""])),
            )
    slugs = {r.uuid: name(r) for r in rows}
    for lock in sorted(locks, key=lambda lock: lock.started):
        age = now - lock.started
        add(
            f"lock {lock.tree}",
            "lock",
            slugs.get(lock.task, lock.task),
            str(lock.tree),
            ago(age),
            "stale: the guard ignores it" if age >= LOCK_STALE_SECONDS else "live",
        )
    tasks = {r.task: name(r) for r in rows}
    for agent in sorted((agent for agents in live.values() for agent in agents), key=lambda a: a.modified):
        used = f"new {count_text(agent.new)}, cache reads {count_text(agent.cache_read)}"
        add(f"agent {agent.path}", "agent", tasks.get(agent.task, str(agent.task)), f"agent-{agent.agent_id}", ago(now - agent.modified), used)
    if not view.rows:
        view.notes.append("no stage, worker lock or agent running in these tasks' repositories")
    return view


def report_view(report: dict, scope: str) -> View:
    """`crew report` as one line per row."""
    lines = render_report(report, scope)
    return View("report", ("REPORT",), [(line,) for line in lines], keys=[str(index) for index in range(len(lines))])


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


@dataclass(frozen=True)
class Watch:
    """What `live_tick` reads between full reads: the open tasks, `{agent_id: latest agent_end}`, and `{task: (session,
    stage start)}` for each open stage whose `stage_start` recorded the orchestrator's `session=`."""

    tasks: list[Path] = field(default_factory=list)
    ended: dict[str, float] = field(default_factory=dict)
    sessions: dict[Path, tuple[str, float]] = field(default_factory=dict)


@dataclass
class Caches:
    """The front end's transcript reads kept between ticks: subagent files (`running_agents`), main sessions."""

    agents: dict[str, Seen] = field(default_factory=dict)
    sessions: dict[str, Seen] = field(default_factory=dict)


def watch_of(rows: list[TaskState], entries: dict[Path, list]) -> Watch:
    running = [r.task for r in rows if head(r) != "DONE"]
    ended = {agent: at for task in running for agent, at in ended_at(entries[task]).items()}
    opened = sorted(
        (at.timestamp(), given["session"], task) for task in running for at, given in stage_pairs(entries[task])[1].values() if given.get("session")
    )
    newest = {session: (task, at) for at, session, task in opened}  # a session counts only toward its newest open stage
    return Watch(running, ended, {task: (session, at) for session, (task, at) in newest.items()})


def read_live(watch: Watch, caches: Caches, claude_dirs: list[Path] | None = None, now: float | None = None) -> dict[Path, list[Live]]:
    """The running agents of the watched tasks, subagents and main sessions, each file read on from the cache's offset."""
    dirs, moment = config_dirs() if claude_dirs is None else claude_dirs, time.time() if now is None else now
    live = running_agents(watch.tasks, dirs, watch.ended, moment, caches.agents)
    for task, agents in session_agents(watch.sessions, dirs, moment, caches.sessions).items():
        live.setdefault(task, []).extend(agents)
    return live


def live_tick(watch: Watch, caches: Caches, claude_dirs: list[Path] | None = None, now: float | None = None) -> tuple[dict[str, str], str]:
    """The fast tick: `{task key: LIVE cell}` and the total over every running agent, from the transcripts alone."""
    live = read_live(watch, caches, claude_dirs, now)
    return {str(task): live_text(agents) for task, agents in live.items()}, live_text([agent for agents in live.values() for agent in agents])


def scope_of(repos: set[str] | None) -> str:
    return "repo " + ", ".join(sorted(repos)) if repos else "every repo"


def load(tasks_dir: Path, filters: Filters, here: Callable[[], dict[str, str]] | None = None) -> tuple[list[TaskState], str]:
    """The filtered rows and their scope line, as `crew ls` selects them."""
    repos = repo_filter(filters.repo) if here is None else repo_filter(filters.repo, here)
    return select(load_rows(tasks_dir), repos, list(filters.states)), scope_of(repos)


def task_trees(rows: list[TaskState]) -> list[Path | None]:
    """Where worker locks can be: the cwd's repository and each open task's recorded checkout (`.task-id` worktree)."""
    recorded = {r.meta.get("worktree") for r in rows if head(r) != "DONE"}
    return [None, *(Path(tree) for tree in sorted(item for item in recorded if isinstance(item, str) and item))]


def collect(
    tasks_dir: Path,
    filters: Filters,
    landed: dict[str, str] | None = None,
    trees: list[Path] | None = None,
    here: Callable[[], dict[str, str]] | None = None,
    now: float | None = None,
    claude_dirs: list[Path] | None = None,
    caches: Caches | None = None,
) -> tuple[dict[str, View], Watch]:
    """Read everything the views show (files, `git worktree list` of each task's repository, and the running agents'
    transcripts in `claude_dirs`, default `config_dirs()`), then `build`; with the `Watch` for `live_tick`. `caches` is
    the front end's per-file cache."""
    rows, scope = load(tasks_dir, filters, here)
    moment = time.time() if now is None else now
    report = gather_report(rows, filters.days, now=datetime.fromtimestamp(moment, UTC))
    entries = {r.task: read_entries(r.task) for r in rows}
    watch = watch_of(rows, entries)
    live = read_live(watch, caches or Caches(), claude_dirs, moment)
    locks = read_locks(worktree_paths(task_trees(rows)) if trees is None else trees)
    return build(rows, filters, scope, entries=entries, locks=locks, report=report, landed=landed, now=moment, live=live), watch


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
