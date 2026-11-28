"""The store: the FTS5 index over unit files, and committing a change to the store's repository.

The index is a rebuildable cache: `refresh` re-reads changed files, drops rows whose file is gone,
and a schema-version change drops the table. `mutate` takes the lock, refuses a merge conflict before
staging, commits anything already dirty, applies the change, reindexes, commits, and restores every
touched file when a step fails.
"""

from __future__ import annotations

import fcntl
import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from crew.core.memory.memory_frontmatter import parse_unit
from crew.core.memory.memory_paths import (
    MemoryStoreError,
    canonical_scope,
    database_path,
    memory_root,
    normalized,
    repo_key,
    scope_directory,
    source_files,
    tokens,
)
from crew.lib.files import atomic_write
from crew.lib.git import GitError, conflicted_paths
from crew.lib.git import dirty_files as _dirty_files
from crew.lib.git import run_git as _run_git

SCHEMA_VERSION = 1


def ensure_store() -> None:
    if not database_path().exists():
        raise MemoryStoreError("memory store missing; run crew-mem.py init")


def connection() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(database_path())
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT count(*) FROM units")
        return conn
    except sqlite3.Error as error:
        raise MemoryStoreError(f"memory store unreadable or corrupt: {error}") from error


def initialize_database() -> None:
    conn = sqlite3.connect(database_path())
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.Error:
        version = 0
    if version not in (0, SCHEMA_VERSION):
        # The index is a rebuildable cache: drop it and let refresh() repopulate.
        conn.execute("DROP TABLE IF EXISTS units")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS units USING fts5(
            id UNINDEXED, type UNINDEXED, scope UNINDEXED, title,
            body, keywords UNINDEXED, paths UNINDEXED, status UNINDEXED,
            review_by UNINDEXED, source_path UNINDEXED, mtime UNINDEXED,
            size UNINDEXED, created UNINDEXED, uses UNINDEXED, helped UNINDEXED,
            misled UNINDEXED, tokenize='porter unicode61'
        )
    """)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.close()


@contextmanager
def store_lock() -> Iterator[None]:
    # Binary mode: this file only carries an flock, and a text open would need an encoding it never uses.
    lock = (memory_root() / ".lock").open("a+b")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def refresh(write_indexes: bool = True) -> sqlite3.Connection:
    """Synchronize changed external units using persisted mtime/size fingerprints."""
    conn = connection()
    indexed = {row["source_path"]: row for row in conn.execute("SELECT id, source_path, mtime, size FROM units")}
    current = set()
    for path in source_files():
        relative = str(path.relative_to(memory_root()))
        current.add(relative)
        stat = path.stat()
        previous = indexed.get(relative)
        if previous and previous["mtime"] == stat.st_mtime_ns and previous["size"] == stat.st_size:
            continue
        conn.execute("DELETE FROM units WHERE source_path = ?", (relative,))
        unit = parse_unit(path)
        conn.execute(
            """
            INSERT INTO units VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                unit["id"],
                unit["type"],
                unit["scope"],
                unit["title"],
                unit["body"],
                json.dumps(unit["keywords"]),
                json.dumps(unit["paths"]),
                unit["status"],
                unit["review_by"],
                unit["source_path"],
                unit["mtime"],
                unit["size"],
                unit["created"],
                unit["uses"],
                unit["helped"],
                unit["misled"],
            ),
        )
    for relative in set(indexed) - current:
        conn.execute("DELETE FROM units WHERE source_path = ?", (relative,))
    conn.commit()
    if write_indexes:
        write_indexes_for_scopes(conn)
    return conn


def write_indexes_for_scopes(conn: sqlite3.Connection) -> list[tuple[Path, str | None]]:
    """Rewrite each scope's `INDEX.md`; returns every path written with its previous content."""
    scopes = {"global"}
    scopes.update(row[0] for row in conn.execute("SELECT DISTINCT scope FROM units"))
    scopes.update(directory.name for directory in (memory_root() / "repos").glob("*") if directory.is_dir())
    backups = []
    for scope in scopes:
        directory = scope_directory(scope)
        if not directory.exists():
            continue
        rows = conn.execute(
            """
            SELECT id, type, title FROM units
            WHERE scope = ? AND status = 'active' AND type != 'observation' ORDER BY id
        """,
            (scope,),
        ).fetchall()
        content = "".join(f"{row['id']} ({row['type']}): {row['title']}\n" for row in rows)
        path = directory / "INDEX.md"
        previous = path.read_text(encoding="utf-8") if path.exists() else None
        if previous != content:
            atomic_write(path, content)
            backups.append((path, previous))
    return backups


def unit_row(conn: sqlite3.Connection, ident: str, scope: str | None = None) -> sqlite3.Row | None:
    """Resolve IDs in the current repository scope before falling back to global."""
    scopes = [canonical_scope(scope)] if scope else [repo_key(), "global"]
    for candidate_scope in scopes:
        row = conn.execute("SELECT * FROM units WHERE id = ? AND scope = ? ORDER BY source_path", (ident, candidate_scope)).fetchone()
        if row:
            return row
    return None


def unit_path(conn: sqlite3.Connection, ident: str, scope: str | None = None) -> Path | None:
    row = unit_row(conn, ident, scope)
    return memory_root() / row["source_path"] if row else None


def run_git(arguments: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Git against the memory store, whose repository is not the caller's working directory."""
    return _run_git(memory_root(), list(arguments), check=check)


def dirty_files() -> list[str]:
    """Paths changed in the memory store, including untracked ones."""
    return _dirty_files(memory_root())


def unresolved_conflicts() -> list[str]:
    """Return conflicted paths, or raise when git cannot answer.

    A failed `git diff` (broken index, missing repo, held lock) is not "no conflicts": reporting
    clean would let `commit_external_changes` adopt conflict markers as the resolution.
    """
    try:
        return conflicted_paths(memory_root())
    except GitError as error:
        raise MemoryStoreError("cannot verify the memory store's merge state: " + str(error)) from error


def git_commit(message: str) -> None:
    result = run_git(["-c", "user.name=mem", "-c", "user.email=mem@localhost", "commit", "-m", message], check=False)
    if result.returncode:
        raise MemoryStoreError(f"git commit failed: {result.stderr.strip() or result.stdout.strip()}")


def commit_external_changes() -> None:
    """Adopt changes already in the store as one commit, refusing across a merge conflict."""
    conflicts = unresolved_conflicts()
    if conflicts:
        raise MemoryStoreError(
            "memory store has unresolved merge conflicts: " + ", ".join(conflicts) + " — resolve them in " + str(memory_root()) + " and retry"
        )
    changes = dirty_files()
    if changes:
        run_git(["add", "-A"])
        git_commit(f"mem: external {len(changes)} files")


def restore_units(backups: list[tuple[Path, str | None]]) -> None:
    """Put every written unit back the way it was, deleting the ones that did not exist."""
    for path, previous in backups:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, previous)


def mutate(operation: str, change: Callable[[], list[tuple[Path, str | None]]], written: list[tuple[Path, str | None]] | None = None) -> int:
    """Lock, preserve changed unit files, index, commit, and restore on failure.

    `written` is a list `change` appends each `(path, previous text)` to before it writes, so a failure
    partway restores what was already written; `change` may also return its backups when it is done.
    """
    ensure_store()
    backups = written if written is not None else []
    with store_lock():
        try:
            commit_external_changes()
            returned = change()
            if returned is not backups:
                backups.extend(returned)
            conn = refresh(write_indexes=False)
            backups.extend(write_indexes_for_scopes(conn))
            conn.close()
            run_git(["add", "-A"])
            if run_git(["diff", "--cached", "--quiet"], check=False).returncode:
                git_commit(operation)
            return 0
        except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryStoreError) as error:
            restore_units(backups)
            print(str(error), file=sys.stderr)
            return 2
        except ValueError:
            # A refused change or a unit `refresh` cannot parse: undo the writes, keep the caller's error.
            restore_units(backups)
            raise


def duplicate_candidates(conn, unit: dict) -> list[str]:
    """Ids of active units in the same scope and type whose title or body nearly matches."""
    candidates = conn.execute(
        """
        SELECT id, title, body FROM units
        WHERE scope = ? AND type = ? AND status = 'active'
    """,
        (unit["scope"], unit["type"]),
    ).fetchall()
    wanted = set(tokens(unit["body"]))
    matches = []
    for candidate in candidates:
        title_match = normalized(candidate["title"]) == normalized(unit["title"])
        existing = set(tokens(candidate["body"]))
        overlap = len(wanted & existing) / len(wanted | existing) if wanted or existing else 0
        if title_match or overlap >= 0.6:
            matches.append(candidate["id"])
    return matches
