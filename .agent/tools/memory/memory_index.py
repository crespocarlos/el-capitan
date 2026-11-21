#!/usr/bin/env python3
"""The FTS5 index: opening it, building it, refreshing it from disk, and resolving unit rows.

The index is a rebuildable cache, never the source of truth: `refresh` re-reads changed unit files
by mtime/size fingerprint and drops rows whose file is gone, so a hand-edited store and an indexed
store converge. `initialize_database` may drop the whole table on a schema-version change for the
same reason.

Committing the store — the lock, the conflict check, and the rollback — lives in `memory_commit`,
because that is a different question from what the index holds.
"""
from __future__ import annotations

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from lib.files import atomic_write
from memory_frontmatter import parse_unit
from memory_paths import (
    MemoryError,
    canonical_scope,
    database_path,
    memory_root,
    repo_key,
    scope_directory,
    source_files,
)

SCHEMA_VERSION = 1


def ensure_store() -> None:
    if not database_path().exists():
        raise MemoryError("memory store missing; run crew-mem.py init")


def connection() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(database_path())
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT count(*) FROM units")
        return conn
    except sqlite3.Error as error:
        raise MemoryError(f"memory store unreadable or corrupt: {error}") from error


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
    indexed = {row["source_path"]: row for row in conn.execute(
        "SELECT id, source_path, mtime, size FROM units"
    )}
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
        conn.execute("""
            INSERT INTO units VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            unit["id"], unit["type"], unit["scope"], unit["title"], unit["body"],
            json.dumps(unit["keywords"]), json.dumps(unit["paths"]), unit["status"],
            unit["review_by"], unit["source_path"], unit["mtime"], unit["size"],
            unit["created"], unit["uses"], unit["helped"], unit["misled"],
        ))
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
        rows = conn.execute("""
            SELECT id, type, title FROM units
            WHERE scope = ? AND status = 'active' AND type != 'observation' ORDER BY id
        """, (scope,)).fetchall()
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
        row = conn.execute(
            "SELECT * FROM units WHERE id = ? AND scope = ? ORDER BY source_path",
            (ident, candidate_scope),
        ).fetchone()
        if row:
            return row
    return None


def unit_path(conn: sqlite3.Connection, ident: str, scope: str | None = None) -> Path | None:
    row = unit_row(conn, ident, scope)
    return memory_root() / row["source_path"] if row else None
