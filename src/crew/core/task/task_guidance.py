"""The context a dispatched agent starts from: repository guidance per path, and ranked memory.

`collect` is the `guidance` verb's record: per directory from the root to a target, `AGENTS.md`, else
`CLAUDE.md`, each file's content once. `memory_context` is `crew-mem.py context` in process, its text or
`(None, reason)` when the store is unavailable, so a caller records the gap instead of an empty file.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sqlite3
from pathlib import Path

from crew.lib.git import GitError, toplevel
from crew.lib.output import DEFAULT_MAX_CHARS


def repo_root(explicit: Path | None) -> Path:
    """The root to resolve targets against: the override, or this checkout's own."""
    if explicit:
        return explicit.resolve()
    try:
        return toplevel(None)
    except GitError as error:
        raise ValueError(str(error)) from error


def guidance_paths(root: Path, target: Path) -> list[Path]:
    """The guidance files that apply to `target`, from the repository root to its directory.

    An `AGENTS.md` wins over a `CLAUDE.md` in the same directory: it is the harness-neutral file,
    and loading both would duplicate every rule for a path that has each.
    """
    resolved = target if target.is_absolute() else Path.cwd() / target
    directory = resolved if resolved.is_dir() else resolved.parent
    try:
        directory = directory.resolve()
        relative = directory.relative_to(root)
    except ValueError as error:
        raise ValueError(f"target is outside repository: {target}") from error

    ancestors = [root]
    current = root
    for part in relative.parts:
        current = current / part
        ancestors.append(current)

    result = []
    for ancestor in ancestors:
        agents = ancestor / "AGENTS.md"
        claude = ancestor / "CLAUDE.md"
        if agents.is_file():
            result.append(agents)
        elif claude.is_file():
            result.append(claude)
    return result


def collect(root: Path, paths: list[Path]) -> dict:
    """`{"root", "files", "targets"}`: each guidance file's content once, and each target's chain or error."""
    files: dict[str, str] = {}
    targets = []
    for path in paths:
        try:
            guidance = guidance_paths(root, path)
            for item in guidance:
                files.setdefault(str(item), item.read_text(encoding="utf-8", errors="replace"))
            targets.append({"path": str(path), "guidance": [str(item) for item in guidance]})
        except (OSError, ValueError) as error:
            targets.append({"path": str(path), "guidance": [], "error": str(error)})
    return {"root": str(root), "files": files, "targets": targets}


def memory_context(mode: str, query: str, paths: list[str], repo: str | None = None, root: Path | None = None) -> tuple[str | None, str]:
    """`(text, "")` from the ranked recall `crew-mem.py context` prints, or `(None, reason)` when it fails.

    The scope is `repo` (`owner/repo` or a bare name), else the checkout at `root`, else the current one."""
    from crew.core.memory.memory_paths import MemoryStoreError, repo_key
    from crew.core.memory.memory_search import context

    scope = repo or (repo_key(root) if root is not None else None)
    args = argparse.Namespace(
        repo=scope, query=query, paths=paths, mode=mode, include_observations=False, json=False, limit=None, max_chars=DEFAULT_MAX_CHARS, warn_unavailable=False
    )
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            context(args)
    except (MemoryStoreError, OSError, sqlite3.Error) as error:
        return None, str(error).splitlines()[0] if str(error) else type(error).__name__
    return printed.getvalue(), ""
