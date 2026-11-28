"""Which file holds a stopped subagent's transcript, and one content-free line saying what was tried.

`agent_transcript_path` is nullable, so `resolve` tries it, then `<conv>/subagents/<id>.jsonl` beside `transcript_path`,
`$CURSOR_TRANSCRIPT_PATH` or it, then any file whose first user line holds the nonce in those folders or in
`~/.cursor/projects/*/agent-transcripts/<conversation id>/subagents/`. An empty candidate is polled up to `WAIT` s.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

WAIT = 3.0
STEP = 0.2


def first_user_line(path: Path) -> str | None:
    """The raw first user line of a transcript, "" when the file has none yet, None when it cannot be read."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict) and "user" in (item.get("type"), item.get("role")):
                    return line
    except OSError:
        return None
    return ""


def subagents_dirs(parent: object) -> list[Path]:
    """`subagents/` beside a conversation transcript, whether it is `<conv>/<conv>.jsonl` or `<conv>.jsonl`."""
    if not isinstance(parent, str) or not parent.strip():
        return []
    path = Path(parent)
    found = [path.parent / "subagents", path.parent / path.stem / "subagents"]
    return list(dict.fromkeys(found))


def candidates(payload: dict, env: dict) -> tuple[list[Path], list[Path]]:
    """The named candidates in order, and the `subagents/` folders a nonce scan may search."""
    ids = [str(payload[key]) for key in ("subagent_id", "child_conversation_id") if payload.get(key)]
    own = payload.get("agent_transcript_path")
    named = [Path(own)] if isinstance(own, str) and own.strip() else []
    folders: list[Path] = []
    for parent in (payload.get("transcript_path"), env.get("CURSOR_TRANSCRIPT_PATH"), own):
        folders.extend(subagents_dirs(parent))
    live = env.get("CURSOR_TRANSCRIPT_PATH")
    convs = [payload.get("parent_conversation_id"), payload.get("conversation_id"), Path(live).stem if isinstance(live, str) and live else None]
    projects = Path(env.get("HOME") or Path.home()) / ".cursor" / "projects"
    for conv in convs:
        if isinstance(conv, str) and conv.strip() and "/" not in conv:
            folders.extend(projects.glob(f"*/agent-transcripts/{conv}/subagents"))
    folders = list(dict.fromkeys(folders))
    named.extend(folder / f"{name}.jsonl" for folder in folders for name in ids)
    return list(dict.fromkeys(named)), folders


def scan(folders: list[Path], needle: str, tried: set[Path]) -> Path | None:
    """The newest file in `folders` not tried yet whose first user line holds `needle`."""
    found = []
    for folder in folders:
        try:
            found.extend(path for path in folder.glob("*.jsonl") if path not in tried)
        except OSError:
            continue
    for path in sorted(found, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
        if needle in (first_user_line(path) or ""):
            return path
    return None


def resolve(payload: dict, wants, needle: str = "", env: dict | None = None, wait: float = WAIT) -> tuple[Path | None, list[Path]]:
    """The first candidate whose first user line `wants` accepts (with `needle`, a nonce scan of the folders comes
    last), and every candidate tried. Polls while a candidate exists with no user line, up to `wait` seconds."""
    named, folders = candidates(payload, dict(os.environ) if env is None else env)
    deadline = time.monotonic() + wait
    while True:
        pending = False
        for path in named:
            line = first_user_line(path) if path.is_file() else None
            if line and wants(line):
                return path, named
            pending = pending or line == ""
        hit = scan(folders, needle, set(named)) if needle else None
        if hit:
            return hit, [*named, hit]
        if not pending or time.monotonic() >= deadline:
            return None, named
        time.sleep(STEP)


def describe(path: Path) -> str:
    """`<path> exists=<0|1> bytes=<n> lines=<n>`: never content."""
    try:
        data = path.read_bytes()
    except OSError:
        return f"{path} exists=0"
    lines = data.count(b"\n")
    return f"{path} exists=1 bytes={len(data)} lines={lines}"


def diagnostic(payload: dict, tried: list[Path]) -> str:
    """One line on why nothing was found: the payload's key names, its ids and paths (values, never content) and each
    candidate's size."""
    keys = ",".join(sorted(payload)) or "none"
    names = ("subagent_id", "agent_transcript_path", "transcript_path", "parent_conversation_id", "conversation_id", "child_conversation_id")
    ids = " ".join(f"{name}={payload.get(name) or '-'}" for name in names)
    paths = "; ".join(describe(path) for path in tried) or "none"
    return f"keys={keys} {ids} status={payload.get('status') or '-'} candidates: {paths}"
