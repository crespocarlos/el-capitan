"""Which file holds a stopped subagent's transcript, and one content-free line saying what was tried.

The hook's normalised event names the candidates its harness's adapter found (`transcripts`, in order) and the
folders a nonce scan may search (`transcript_dirs`): `resolve` tries each candidate, then any file whose first user
line holds the nonce in those folders. An empty candidate is polled up to `WAIT` s.
"""

from __future__ import annotations

import json
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


def candidates(event: dict) -> tuple[list[Path], list[Path]]:
    """The named candidates in order, and the folders a nonce scan may search."""
    named, folders = event.get("transcripts"), event.get("transcript_dirs")
    return [Path(path) for path in named if isinstance(path, str)] if isinstance(named, list) else [], [
        Path(path) for path in folders if isinstance(path, str)
    ] if isinstance(folders, list) else []


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


def resolve(event: dict, wants, needle: str = "", wait: float = WAIT) -> tuple[Path | None, list[Path]]:
    """The first candidate whose first user line `wants` accepts (with `needle`, a nonce scan of the folders comes
    last), and every candidate tried. Polls while a candidate exists with no user line, up to `wait` seconds."""
    named, folders = candidates(event)
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


def diagnostic(event: dict, tried: list[Path]) -> str:
    """One line on why nothing was found: the harness payload's key names (`keys`), the ids and folders (values, never
    content) and each candidate's size."""
    keys = ",".join(event.get("keys") or []) or "none"
    ids = " ".join(f"{name}={event.get(name) or '-'}" for name in ("harness", "agent_id", "session"))
    folders = ",".join(event.get("transcript_dirs") or []) or "-"
    paths = "; ".join(describe(path) for path in tried) or "none"
    return f"keys={keys} {ids} folders={folders} status={event.get('status') or '-'} candidates: {paths}"
