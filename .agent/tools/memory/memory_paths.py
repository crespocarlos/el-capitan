#!/usr/bin/env python3
"""Where the memory store lives, and how a scope names a directory inside it.

The base of the memory package's dependency chain: roots, the database path, repository scope,
and the text normalization every other module shares. Nothing here opens the index, parses a unit,
or prints a command result, so every module above can import it without a cycle.

Scope is the upstream repository's bare name, so a fork and its worktrees share one store. Git
failing to answer is not an error for a scope — the store must still open — which is why
`repo_key` falls back to the directory name.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path
from typing import Iterator

from lib.git import GitError, remotes, remote_url, toplevel


class MemoryError(Exception):
    """Expected unavailable/corrupt-store error."""


def memory_root() -> Path:
    return Path(os.environ.get("CREW_MEMORY_DIR", Path.home() / ".agent" / "memory"))


def journal_root() -> Path:
    return Path(os.environ.get("CREW_JOURNAL_DIR", Path.home() / ".agent" / "journal"))


def database_path() -> Path:
    return memory_root() / ".index.sqlite"


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "memory"


def today() -> str:
    return dt.date.today().isoformat()


def tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", value.lower())


def repo_key() -> str:
    """The repository scope: the upstream (or origin) repository's bare name, else the directory.

    One `toplevel` and one `remote_url` per remote answer what three hand-rolled calls used to ask:
    a fork's `upstream` wins over `origin`, and a checkout with neither falls back to its directory
    name. Git failing here is not an error for a scope — the memory store must still open — so the
    directory fallback covers an unreadable or absent repository.
    """
    try:
        top = toplevel(None)
    except GitError:
        return Path.cwd().name
    for remote_name in ["upstream", "origin", *remotes(top)]:
        url = remote_url(top, remote_name)
        if not url:
            continue
        match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
        if match:
            return match.group(2)
    return top.name


def canonical_scope(value: str) -> str:
    if value == "global":
        return "global"
    value = value.removeprefix("repo:")
    owner_repo = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/([A-Za-z0-9._-]+?)(?:\.git)?", value)
    return owner_repo.group(1) if owner_repo else value


def scope_directory(scope: str) -> Path:
    scope = canonical_scope(scope)
    return memory_root() / ("global" if scope == "global" else f"repos/{scope}")


def observation_directory(scope: str) -> Path:
    scope = canonical_scope(scope)
    if scope in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", scope):
        raise ValueError(f"invalid observation scope: {scope!r}")
    return memory_root() / "observations" / scope


def scope_from_path(path: Path) -> str:
    """The scope a stored unit's own path implies, for a file whose frontmatter omits one."""
    relative = path.relative_to(memory_root())
    if relative.parts[0] == "global":
        return "global"
    if len(relative.parts) >= 2 and relative.parts[0] in {"repos", "observations"}:
        return relative.parts[1]
    return repo_key()


def source_files() -> Iterator[Path]:
    """Every stored unit file, across global, every repository, and every observation scope."""
    root = memory_root()
    for directory in [
        root / "global", *(root / "repos").glob("*"), *(root / "observations").glob("*")
    ]:
        if directory.is_dir():
            yield from sorted(
                file for file in directory.glob("*.md")
                if file.name not in {"INDEX.md", "MEMORY.md"}
            )
