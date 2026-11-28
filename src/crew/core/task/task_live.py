"""Tokens in use by running agents, from their transcripts `<config dir>/projects/*/*/subagents/agent-<id>.jsonl`
and the orchestrator's own `<config dir>/projects/*/<session>.jsonl` named at `stage_start` (`session_agents`).
Bounded: only the config dirs given, `subagents` dirs changed within `SESSION_WINDOW`, transcripts modified within
`WINDOW`, and only the first user line of a transcript naming no task asked for. Usage is summed from assistant
lines (`task_usage.usage`); `cache` keeps each file's offset and calls. An agent runs while its file is fresh and its
last assistant message is newer than its latest `agent_end`. Nothing writes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from crew.core.task.task_lock import LOCK_STALE_SECONDS
from crew.core.task.task_progress import Entry, agent_ends, new_tokens
from crew.core.task.task_usage import TASK_LINE, text_of, usage

WINDOW = 15 * 60  # seconds: a transcript quiet for longer is not running
SESSION_WINDOW = LOCK_STALE_SECONDS  # a `subagents` dir with no agent added for longer holds no running agent


@dataclass
class Seen:
    """One transcript as read so far: the byte offset after its last whole line read, the task its first user line
    names (its real path; "" when it names none, None before that line), its assistant usage by message id, and the
    time of its last assistant message (None before one carries a readable `timestamp`). Usage stamped before `since`
    is skipped (a main session counts from its stage's start)."""

    offset: int = 0
    task: str | None = None
    calls: dict[str, dict] = field(default_factory=dict)
    said: float | None = None
    since: float = 0.0


def seconds(stamp: object) -> float | None:
    """An ISO `timestamp` (`Z` or an offset) as epoch seconds; None when it does not parse."""
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp).timestamp()
    except ValueError:
        return None


@dataclass(frozen=True)
class Live:
    """One running agent: its task, id, transcript and modification time, and its new tokens and cache reads so far."""

    task: Path
    agent_id: str
    path: Path
    modified: float
    new: int
    cache_read: int


def real(path: str | Path) -> str:
    return os.path.realpath(os.path.expanduser(str(path)))


def ended_at(entries: list[Entry]) -> dict[str, float]:
    """`{agent_id: time of its latest agent_end}` for one task's entries."""
    return {given["agent_id"]: entry.at.timestamp() for entry, given in agent_ends(entries) if given.get("agent_id") and entry.at is not None}


def subdirs(path: Path) -> list[Path]:
    try:
        return [Path(item.path) for item in os.scandir(path) if item.is_dir()]
    except OSError:
        return []


def modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def candidates(config_dirs: list[Path], now: float) -> list[Path]:
    """Every `agent-*.jsonl` modified within `WINDOW`, in the `subagents` directories that changed within
    `SESSION_WINDOW` (a directory's mtime moves only when an agent file is added, never as one is written)."""
    found = []
    for config in config_dirs:
        for project in subdirs(config / "projects"):
            for session in subdirs(project):
                agents = session / "subagents"
                if now - modified(agents) <= SESSION_WINDOW:
                    fresh = (path for path in sorted(agents.glob("agent-*.jsonl")) if now - modified(path) <= WINDOW)
                    found.extend(fresh)
    return found


def advance(path: Path, seen: Seen, wanted: set[str]) -> None:
    """Read `path` on from `seen.offset`, whole lines only: up to its first user line, and further only when that
    line names a task in `wanted`. Raises OSError for an unreadable file."""
    if seen.task is not None and seen.task not in wanted:
        return
    with path.open("rb") as handle:
        handle.seek(seen.offset)
        for line in iter(handle.readline, b""):
            if not line.endswith(b"\n"):
                return  # a line still being written: the next read takes it whole
            seen.offset += len(line)
            try:
                item = json.loads(line)
            except ValueError:
                continue
            message = item.get("message") if isinstance(item, dict) else None
            if not isinstance(message, dict):
                continue
            if seen.task is None:
                if item.get("type") == "user":
                    named = TASK_LINE.search(text_of(message.get("content")))
                    seen.task = real(named.group(1)) if named else ""
                    if seen.task not in wanted:
                        return
                continue
            if item.get("type") != "assistant":
                continue
            seen.said = seconds(item.get("timestamp")) or seen.said
            if isinstance(message.get("usage"), dict) and (seen.said or 0) >= seen.since:
                key = str(message.get("id") or f"#{seen.offset}")
                seen.calls[key] = {"type": "assistant", "message": {"id": key, "usage": message["usage"]}}


def running_agents(
    tasks: list[Path], config_dirs: list[Path], ended: dict[str, float], now: float, cache: dict[str, Seen] | None = None
) -> dict[Path, list[Live]]:
    """`{task: [Live]}` for the agents of `tasks` still running; `ended` is `{agent_id: latest agent_end time}`.

    `cache` (a dict the caller keeps between refreshes) holds a `Seen` per file by real path, dropped once the file is
    quiet past `WINDOW`; without one every file is read cold. A file reached through two config dirs counts once.
    """
    cache = {} if cache is None else cache
    for name in [name for name in cache if now - modified(Path(name)) > WINDOW]:
        del cache[name]
    wanted = {real(task): task for task in tasks}
    paths: dict[str, Path] = {}
    for path in [*candidates(config_dirs, now), *(Path(name) for name, seen in cache.items() if seen.task in wanted)]:
        paths.setdefault(real(path), path)
    found: dict[Path, list[Live]] = {}
    for key, path in paths.items():
        agent_id = path.stem[len("agent-") :]
        stamp = modified(path)
        if now - stamp > WINDOW:
            continue
        seen = cache.setdefault(key, Seen())
        try:
            advance(path, seen, set(wanted))
        except OSError:
            continue
        # The hook writes `agent_end` before the transcript's last write, so the file's mtime cannot tell a finished
        # agent from a resumed one; its last assistant message can, compared at the stamp's one-second resolution.
        finished = agent_id in ended and (seen.said is None or int(seen.said) <= ended[agent_id])
        if seen.task in wanted and not finished:
            found.setdefault(wanted[seen.task], []).append(live(wanted[seen.task], agent_id, path, stamp, seen))
    return found


def live(task: Path, agent_id: str, path: Path, stamp: float, seen: Seen) -> Live:
    counts = usage(list(seen.calls.values())) or {"cache_read": 0}  # no call yet: running, nothing used
    return Live(task, agent_id, path, stamp, new_tokens(counts), counts["cache_read"])


def session_agents(sessions: dict[Path, tuple[str, float]], config_dirs: list[Path], now: float, cache: dict[str, Seen]) -> dict[Path, list[Live]]:
    """`{task: [Live "main"]}` for `{task: (session id, stage start)}`: the session's own transcript while it is fresh,
    its calls since the stage started. `cache` is the caller's, keyed by file and start, apart from `running_agents`'."""
    found: dict[Path, list[Live]] = {}
    for task, (session, since) in sessions.items():
        path = next((p for config in config_dirs for p in (config / "projects").glob(f"*/{session}.jsonl") if now - modified(p) <= WINDOW), None)
        if path is None:
            continue
        seen = cache.setdefault(f"{real(path)}@{since}", Seen(task=real(task), since=since))
        try:
            advance(path, seen, {real(task)})
        except OSError:
            continue
        found[task] = [live(task, "main", path, modified(path), seen)]
    return found
