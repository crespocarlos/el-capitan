"""The crew TUI's reads: `collect` reads tasks, each task repository's worker locks, the report, agents' transcripts,
the runs ledger (`lib/runs.py`) and takes the cached GitHub facts, then builds the tabs (`tui_views`); `live_tick`
reads only new transcript lines, for LIVE; `render` prints a view (`--once`). It never writes, runs a command, calls a
model or reads GitHub (`tui_github` does, for the app)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crew.core.task.ls_data import load_rows, local_remotes, repo_filter, select
from crew.core.task.ls_report import gather as gather_report
from crew.core.task.ls_report import stage_pairs
from crew.core.task.task_live import Live, Seen, ended_at, running_agents, session_agents
from crew.core.task.task_lock import read_locks, worktree_paths
from crew.core.task.task_progress import read_entries
from crew.core.task.task_report import aligned, fitted
from crew.core.task.task_state import TaskState, head
from crew.core.task.task_status import StatusError, token
from crew.lib.runs import read_runs
from crew.tui.tui_github import Facts
from crew.tui.tui_views import TABS, Snapshot, View, ago, build, expanded, live_text


@dataclass(frozen=True)
class Filters:
    """What the tabs filter on: `repo` (None: `ls.repo` of config.json; `here`; `all`), states, words every shown task
    must contain (`/` in the app), and the cost window in days."""

    repo: str | None = None
    states: tuple[str, ...] = ()
    text: tuple[str, ...] = ()
    days: int = 30


def parse_filter(text: str, base: Filters | None = None) -> Filters:
    """`repo:R status:S [status:T] word…` applied over `base` (the current filter).

    The text replaces the states and words; repo and days stay as `base` has them unless the text sets repo. A word
    with no colon is matched against each task's name, repository, state and issue and PR numbers. An unknown `key:`
    or status raises ValueError.
    """
    base = base or Filters()
    repo, states, words = base.repo, [], []
    for word in text.split():
        key, colon, value = word.partition(":")
        if key == "repo" and value:
            repo = value
        elif key == "status" and value:
            try:
                states.append(token(value) or value.upper())
            except StatusError as error:
                raise ValueError(str(error)) from error
        elif not colon:
            words.append(word.lower())
        else:
            raise ValueError(f"unknown filter {word!r}: use repo:OWNER/NAME, status:STATE or a word")
    return Filters(repo=repo, states=tuple(states), text=tuple(words), days=base.days)


def freshness(facts: Facts, now: float) -> str:
    """The header's GitHub part: the age of the facts shown, and the last read's error (offline, or a partial read)."""
    if facts.fetched_at is None:
        return f"GitHub offline ({facts.error}), no data" if facts.error else "GitHub reading…"
    return f"GitHub {ago(now - facts.fetched_at)} ago" + (f" ({facts.error})" if facts.error else "")


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
    stage start)}` for each open stage whose `stage_start` recorded the orchestrator's `session=`; and every task's PR
    and issue URLs and `{owner/repo: local clone}`, for the GitHub read."""

    tasks: list[Path] = field(default_factory=list)
    ended: dict[str, float] = field(default_factory=dict)
    sessions: dict[Path, tuple[str, float]] = field(default_factory=dict)
    urls: list[str] = field(default_factory=list)
    clones: dict[str, Path] = field(default_factory=dict)


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
    urls = [url for r in rows for url in (r.issue, *r.prs) if url]
    return Watch(running, ended, {task: (session, at) for session, (task, at) in newest.items()}, urls, clones_of(rows))


def clones_of(rows: list[TaskState]) -> dict[str, Path]:
    """`{owner/repo: local clone}`: the current directory's repository, then each task's recorded worktree that exists."""
    trees = {r.repo.lower(): Path(tree) for r in rows if r.repo and isinstance(tree := r.meta.get("worktree"), str) and Path(tree).is_dir()}
    return {**dict.fromkeys(local_remotes(), Path.cwd()), **trees}


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
    facts: Facts | None = None,
    trees: list[Path] | None = None,
    here: Callable[[], dict[str, str]] | None = None,
    now: float | None = None,
    claude_dirs: list[Path] | None = None,
    caches: Caches | None = None,
) -> tuple[dict[str, View], Watch]:
    """Read everything the views show (files, `git worktree list` of each task's repository, the running agents'
    transcripts in `claude_dirs`, default `config_dirs()`, and the runs ledger), then `build` with `facts`; with the
    `Watch` for `live_tick` and the GitHub read. `caches` is the front end's per-file cache."""
    rows, scope = load(tasks_dir, filters, here)
    moment = time.time() if now is None else now
    report = gather_report(rows, filters.days, now=datetime.fromtimestamp(moment, UTC))
    entries = {r.task: read_entries(r.task) for r in rows}
    watch = watch_of(rows, entries)
    live = read_live(watch, caches or Caches(), claude_dirs, moment)
    locks = read_locks(worktree_paths(task_trees(rows)) if trees is None else trees)
    views = build(rows, filters.text, scope, report, Snapshot(entries, locks, moment, live, facts or Facts(), read_runs()))
    return views, watch


def render(view: View, width: int = 0) -> list[str]:
    """A view as aligned plain text: the title, the table with every child row (cut to `width` columns, NOTE first and
    then TASK, when `width` is set), the notes."""
    view = expanded(view, set(view.children))
    table = [view.header, *view.rows]
    return [f"== {TABS.get(view.title, view.title)} ==", *aligned(fitted(table, width) if width > 0 else table), *view.notes]
