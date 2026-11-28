#!/usr/bin/env python3
"""Where the memory store lives, and how a scope names a directory inside it.

The base of the memory package (roots, database path, scope, text normalization); it imports no
other memory module. Scope is the upstream repository's bare name, so a fork and its worktrees share
one store; when git cannot answer, `repo_key` falls back to the directory name.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Iterator
from pathlib import Path

from crew.lib.git import GitError, remote_url, remotes, repo_name_from_url, toplevel


class MemoryStoreError(Exception):
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


def repo_key(directory: Path | None = None) -> str:
    """The repository scope of `directory` (default: the cwd): the upstream (or origin) repository's bare name.

    A fork's `upstream` wins over `origin`; a local-path or file:// remote gives its last path
    segment (`lib.git.repo_name_from_url`), so existing scopes keep their key. Git failing is not an
    error for a scope (the store must still open): the directory name is the fallback.
    """
    try:
        top = toplevel(directory)
    except GitError:
        return (directory or Path.cwd()).name
    for remote_name in ["upstream", "origin", *remotes(top)]:
        url = remote_url(top, remote_name)
        if not url:
            continue
        found = repo_name_from_url(url)
        if found:
            return found
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
    for directory in [root / "global", *(root / "repos").glob("*"), *(root / "observations").glob("*")]:
        if directory.is_dir():
            yield from sorted(file for file in directory.glob("*.md") if file.name not in {"INDEX.md", "MEMORY.md"})
