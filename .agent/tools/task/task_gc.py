"""Retention of local state: `crew-task.py gc` (a dry run unless `--apply`) and the sizes `crew-doctor.py` checks.

`~/.agent/config.json` holds `gc`, `doctor`, `ls` (`ls.repo`: the scope of `crew ls` without `--repo`) and `mcp`
(server names doctor looks for, empty by default); an unset key takes its default. The policy: a DONE task's
`artifacts/` after `artifacts_days`, the DONE task archived after `archive_days`, memory `.sessions` files after
`sessions_days` (never the review queue) and the hook logs' lines (`STATE_LOGS`), and the legacy `~/.agent/telemetry`.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import shutil
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

from task_lock import LOCK_NAME
from task_state import last_activity
from task_status import head, read_status

from lib.clock import utc_stamp
from lib.files import atomic_write, read_json_object

DEFAULTS = {"gc": {"artifacts_days": 14, "archive_days": 90, "sessions_days": 30},
            "doctor": {"tasks_mb": 500, "sessions_mb": 100},
            "ls": {"repo": "here"},
            "mcp": {"docs": [], "code_search": []}}  # project-agnostic: the user names their own servers
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SERVER_NAME = re.compile(r"[A-Za-z0-9_-]+")  # install_blocks.SERVER_NAME: the characters a tool id keeps
# A section's accepted values when not a number >= 0.
RULES = {"ls": "all, here or an owner/name", "mcp": "a list of MCP server names (letters, digits, _ and -)"}
KEEP_SESSIONS = frozenset({"review-queue.jsonl"})  # the capture queue `crew-inbox.py` drains
TELEMETRY_NOTICE = "legacy telemetry: it holds raw shell commands and nothing reads it"
# Hook logs under ~/.agent/state, each line opening with its UTC stamp: pruned line by line after `sessions_days`.
STATE_LOGS = ("capture-reply.log", "cursor-usage.log", "cursor-conversations.txt")
DAY = 86400


class ConfigError(ValueError):
    """An unreadable or invalid `config.json`: the command names the file and exits 2."""


@dataclass(frozen=True)
class Places:
    """Where the state lives: `~/.agent`, its tasks, and the memory store (`CREW_MEMORY_DIR`)."""

    agent: Path
    tasks: Path
    memory: Path

    @classmethod
    def here(cls, tasks: Path | None = None) -> Places:
        agent = Path.home() / ".agent"
        return cls(agent, tasks or agent / "tasks", Path(os.environ.get("CREW_MEMORY_DIR", agent / "memory")))


@dataclass(frozen=True)
class Action:
    verb: str  # "remove", "archive" or "prune" (a log's lines stamped before `before`)
    path: Path
    reason: str
    size: int
    before: float = 0.0


def valid(section: str, value: object) -> bool:
    """`ls.repo` is `all`, `here` or an `owner/name`; an `mcp` key, a list of server names; any other, a number >= 0."""
    if section == "ls":
        return isinstance(value, str) and (value.lower() in ("all", "here") or bool(REPO_NAME.match(value)))
    if section == "mcp":
        return isinstance(value, list) and all(isinstance(name, str) and SERVER_NAME.fullmatch(name) for name in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def load_config(agent: Path) -> dict:
    """The defaults overlaid with `<agent>/config.json`; an unknown key or an invalid value is a ConfigError."""
    merged = {section: dict(values) for section, values in DEFAULTS.items()}
    path = agent / "config.json"
    if not path.exists():
        return merged
    try:
        data = read_json_object(path)
    except ValueError as error:
        raise ConfigError(str(error)) from error
    for section, given in data.items():
        if section not in DEFAULTS or not isinstance(given, dict):
            raise ConfigError(f"{path}: {section!r} is not one of {sorted(DEFAULTS)} as an object")
        for key, value in given.items():
            if key not in DEFAULTS[section] or not valid(section, value):
                raise ConfigError(f"{path}: {section}.{key} must be one of {sorted(DEFAULTS[section])}, "
                                  f"{RULES.get(section, 'a number >= 0')}")
            merged[section][key] = value
    return merged


def size_of(path: Path) -> int:
    """Bytes under `path`, symlinks counted as links and never followed."""
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        total += sum(os.lstat(os.path.join(root, name)).st_size for name in files)
    return total


def done_tasks(tasks: Path) -> list[Path]:
    """Task directories (never a symlink) whose SPEC.md status is DONE."""
    found = []
    for task in sorted(tasks.glob("*")) if tasks.is_dir() else []:
        spec = task / "SPEC.md"
        if task.is_dir() and not task.is_symlink() and spec.is_file() and head(read_status(spec)) == "DONE":
            found.append(task)
    return found


def newest_file(task: Path) -> float:
    """The newest modification time of anything in the task directory, never following a link."""
    times = [task.lstat().st_mtime]
    for root, dirs, files in os.walk(task):
        times += [os.lstat(os.path.join(root, name)).st_mtime for name in dirs + files]
    return max(times)


def under(path: Path, parent: Path) -> bool:
    resolved, base = path.resolve(), parent.resolve()
    return resolved == base or base in resolved.parents


def plan(places: Places, policy: dict, now: float | None = None, notes: list[str] | None = None) -> list[Action]:
    """Every path the policy selects, nothing touched: artifacts, archives, session files, telemetry.

    A task's age is its last activity: the newest PROGRESS entry or file in it, whichever is later. A task
    holding a worker lock, and a `.sessions` that is a link or resolves outside `~/.agent`, are skipped
    with a line in `notes`.
    """
    now = time.time() if now is None else now
    notes = [] if notes is None else notes
    actions = []
    for task in done_tasks(places.tasks):
        if (task / LOCK_NAME).exists():
            notes.append(f"skipped {shown(task)}: a worker holds {LOCK_NAME}")
            continue
        days = int((now - max(last_activity(task), newest_file(task))) / DAY)
        artifacts = task / "artifacts"
        removed = 0
        if days > policy["artifacts_days"] and artifacts.is_dir() and not artifacts.is_symlink():
            removed = size_of(artifacts)
            reason = f"DONE {days} days ago (artifacts after {policy['artifacts_days']})"
            actions.append(Action("remove", artifacts, reason, removed))
        if days > policy["archive_days"]:
            reason = f"DONE {days} days ago (archived after {policy['archive_days']})"
            actions.append(Action("archive", task, reason, size_of(task) - removed))
    sessions = places.memory / ".sessions"
    cutoff = now - policy["sessions_days"] * DAY
    usable = sessions.is_dir() and not sessions.is_symlink() and under(sessions, places.agent)
    if sessions.is_dir() and not usable:
        notes.append(f"skipped {shown(sessions)}: a link or outside ~/.agent, so its files are not this install's")
    for path in sorted(sessions.iterdir()) if usable else []:
        if (path.is_file() and not path.is_symlink() and path.name not in KEEP_SESSIONS
                and path.stat().st_mtime < cutoff):
            reason = f"session file older than {policy['sessions_days']} days"
            actions.append(Action("remove", path, reason, size_of(path)))
    telemetry = places.agent / "telemetry"
    if telemetry.exists() or telemetry.is_symlink():
        actions.append(Action("remove", telemetry, TELEMETRY_NOTICE, size_of(telemetry)))
    for path in (places.agent / "state" / name for name in STATE_LOGS):
        old = old_bytes(path, cutoff)
        if old:
            reason = f"log lines older than {policy['sessions_days']} days"
            actions.append(Action("prune", path, reason, old, cutoff))
    return actions


def stamp_of(line: str) -> float | None:
    """The time of a line that opens with a `YYYY-MM-DDTHH:MM:SSZ` stamp, else None (such a line is kept)."""
    try:
        return calendar.timegm(time.strptime(line[:20], "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def old_lines(path: Path, cutoff: float) -> tuple[list[str], list[str]]:
    """The log's lines `(kept, dropped)`: dropped are those stamped before `cutoff`; none for a missing file or link."""
    if not path.is_file() or path.is_symlink():
        return [], []
    kept, dropped = [], []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True):
        stamp = stamp_of(line)
        (dropped if stamp is not None and stamp < cutoff else kept).append(line)
    return kept, dropped


def old_bytes(path: Path, cutoff: float) -> int:
    return sum(len(line.encode()) for line in old_lines(path, cutoff)[1])


def delete(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


class ApplyError(OSError):
    """A step of `apply` failed; `done` lists the paths already removed or archived before it."""

    def __init__(self, error: OSError, path: Path, done: list[str]) -> None:
        super().__init__(f"{shown(path)}: {error}")
        self.done = done


def apply(actions: list[Action], places: Places) -> Path | None:
    """Remove, then archive the selected tasks into one tarball under `~/.agent/archive`; returns the tarball."""
    done: list[str] = []
    current = places.agent
    try:
        for action in actions:
            current = action.path
            if action.verb == "remove" and (action.path.exists() or action.path.is_symlink()):
                delete(action.path)
                done.append(shown(action.path))
            if action.verb == "prune":
                kept, dropped = old_lines(action.path, action.before)
                if dropped:
                    atomic_write(action.path, "".join(kept))
                    done.append(f"{shown(action.path)} ({len(dropped)} lines)")
        archived = [action.path for action in actions if action.verb == "archive"]
        if not archived:
            return None
        target = current = places.agent / "archive" / f"tasks-{utc_stamp().replace(':', '')}.tar.gz"
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w:gz") as tar:
            for task in archived:
                tar.add(task, arcname=task.name)
        for task in archived:
            current = task
            shutil.rmtree(task)
            done.append(f"{shown(task)} (archived in {shown(target)})")
    except OSError as error:
        raise ApplyError(error, current, done) from error
    return target


def shown(path: Path, home: Path | None = None) -> str:
    """`path` with HOME (or `home`) written as `~`."""
    base, text = str(home or Path.home()), str(path)
    return "~" + text[len(base):] if text.startswith(base + os.sep) else text


def megabytes(size: int) -> str:
    return f"{size / 1e6:.1f} MB"


def report(actions: list[Action], applied: bool) -> list[str]:
    """One line per task action, the session files as one line, and the total."""
    lines = []
    sessions = [a for a in actions if a.reason.startswith("session file")]
    for action in actions:
        if action not in sessions:
            verb = action.verb + "d" if applied else "would " + action.verb
            lines.append(f"  {verb:<14} {shown(action.path)}  {megabytes(action.size)}  {action.reason}")
    if sessions:
        verb = "removed" if applied else "would remove"
        lines.append(f"  {verb:<14} {len(sessions)} file(s) in {shown(sessions[0].path.parent)}  "
                     f"{megabytes(sum(a.size for a in sessions))}  {sessions[0].reason}")
    total = sum(a.size for a in actions)
    tail = "" if applied or not actions else "; run with --apply to act"
    lines.append(f"{len(actions)} path(s), {megabytes(total)}{tail}" if actions else "nothing to collect")
    return lines


def main(args) -> int:
    """`crew-task.py gc [--only telemetry] [--apply] [--json]`: print the plan, and with `--apply` carry it out."""
    places = Places.here(args.tasks_dir)
    try:
        policy = load_config(places.agent)["gc"]
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    notes: list[str] = []
    actions = plan(places, policy, notes=notes)
    if getattr(args, "only", None) == "telemetry":
        actions, notes = [a for a in actions if a.path == places.agent / "telemetry" or a.verb == "prune"], []
    tarball = None
    if args.apply:
        try:
            tarball = apply(actions, places)
        except ApplyError as error:
            done = "; ".join(error.done) or "nothing"
            print(f"error: {error}. Already done: {done}. Run crew-task.py gc again to see what is left.",
                  file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps([{"verb": a.verb, "path": str(a.path), "bytes": a.size, "reason": a.reason,
                           **({"archive": str(tarball)} if tarball and a.verb == "archive" else {})} for a in actions]))
        for note in notes:
            print(note, file=sys.stderr)
        return 0
    print(f"crew gc ({'applied' if args.apply else 'dry run; --apply acts'}): policy {json.dumps(policy)}")
    print("\n".join(report(actions, args.apply) + notes))
    if tarball:
        print(f"archived into {shown(tarball)}")
    return 0
