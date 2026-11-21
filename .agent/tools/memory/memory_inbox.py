#!/usr/bin/env python3
"""The store's inbox: drafting a verdict for a draft, and importing it into the store.

A draft in `.inbox` is a candidate unit a session left for review. `inbox_report` says what
importing it would do — NOOP, UPDATE, SUPERSEDE, ADD — before anything is written, so approving a
draft is a decision about a stated outcome rather than about a filename. `apply_inbox` is the write:
it imports the unit, removes the consumed draft, and restores every file when a step fails.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib.files import atomic_write
from memory_commit import commit_external_changes, git_commit, run_git
from memory_frontmatter import parse_unit, render_unit
from memory_index import ensure_store, refresh, write_indexes_for_scopes
from memory_paths import (
    MemoryError,
    memory_root,
    normalized,
    repo_key,
    scope_directory,
    slug,
)
from memory_index import store_lock
from memory_commit import restore_units
from memory_store import duplicate_candidates


def inbox_report(conn: sqlite3.Connection, source: Path) -> str:
    """The verdict for one inbox draft: NOOP, UPDATE, SUPERSEDE, ADD, or an inbox error."""
    try:
        candidate = parse_unit(source, inferred_scope=repo_key())
    except (OSError, ValueError) as error:
        return f"inbox error: {source.name}: {error}"
    existing = conn.execute("""
        SELECT id, title, body FROM units
        WHERE scope = ? AND type = ? AND status = 'active'
    """, (candidate["scope"], candidate["type"])).fetchall()
    exact = next((row for row in existing if row["body"] == candidate["body"]), None)
    same_title = next(
        (row for row in existing if normalized(row["title"]) == normalized(candidate["title"])),
        None,
    )
    overlap = duplicate_candidates(conn, candidate)
    if exact:
        return f"NOOP inbox: {source.name} matches {exact['id']}"
    if same_title:
        return f"UPDATE inbox: {source.name} replaces {same_title['id']}"
    if overlap:
        return f"SUPERSEDE inbox: {source.name} overlaps {' '.join(overlap)}"
    return f"ADD inbox: {source.name}"


def imported_path(unit: dict) -> Path:
    """Where an imported unit lands, suffixed with its id when the name is already taken."""
    base = scope_directory(unit["scope"]) / f"{unit['type']}_{slug(unit['title'])}.md"
    if not base.exists():
        return base
    try:
        if parse_unit(base)["id"] == unit["id"]:
            return base
    except ValueError:
        pass
    return scope_directory(unit["scope"]) / f"{unit['type']}_{slug(unit['title'])}-{unit['id'][:8]}.md"


def gather_inbox(
    conn: sqlite3.Connection, sources: list[Path]
) -> tuple[list[tuple[Path, str]], list[Path], list[str], list[str], list[str]]:
    """Parse the chosen drafts; returns writes, removals, errors, duplicates, and imported ids.

    The ids are captured here because the import removes each draft, so nothing later can read its
    frontmatter. They are what a caller sees: an `id:` is the handle every other command accepts,
    while the filename is only where the draft happened to live.
    """
    writes, removals, errors, duplicates, ids = [], [], [], [], []
    for source in sources:
        if not source.exists():
            errors.append(f"inbox file not found: {source.name}")
            continue
        try:
            unit = parse_unit(source, inferred_scope=repo_key())
        except (OSError, ValueError) as error:
            errors.append(f"parse error: {source.name}: {error}")
            continue
        candidate_duplicates = duplicate_candidates(conn, unit)
        if candidate_duplicates:
            duplicates.append(f"{source.name}: duplicate {' '.join(candidate_duplicates)}")
            continue
        target = imported_path(unit)
        writes.append((target, render_unit(unit)))
        removals.append(source)
        ids.append(unit["id"])
    return writes, removals, errors, duplicates, ids


def apply_inbox(writes: list[tuple[Path, str]], removals: list[Path]) -> int:
    """Write the imported units, remove the consumed drafts, and commit; 0 or 2 on failure."""
    backups: list[tuple[Path, str | None]] = []
    try:
        commit_external_changes()
        for path, rendered in writes:
            previous = path.read_text(encoding="utf-8") if path.exists() else None
            atomic_write(path, rendered)
            backups.append((path, previous))
        for source in removals:
            backups.append((source, source.read_text(encoding="utf-8")))
            source.unlink()
        refreshed = refresh(write_indexes=False)
        backups.extend(write_indexes_for_scopes(refreshed))
        refreshed.close()
        run_git(["add", "-A"])
        git_commit(f"mem: import-inbox {len(writes)} units")
    except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryError) as error:
        restore_units(backups)
        print(str(error), file=sys.stderr)
        return 2
    return 0


def import_inbox(args: argparse.Namespace) -> int:
    """Import the whole inbox or the named drafts, reporting each verdict."""
    ensure_store()
    inbox = memory_root() / ".inbox"
    wanted = set(args.files or [])
    sources = sorted(inbox.glob("*.md")) if args.all or not wanted else [
        inbox / name for name in wanted
    ]
    if not sources:
        print("no changes")
        return 0
    with store_lock():
        conn = refresh(write_indexes=False)
        writes, removals, errors, duplicates, ids = gather_inbox(conn, sources)
        if writes:
            code = apply_inbox(writes, removals)
            if code:
                return code
        for ident in ids:
            print(ident)
        for error in errors:
            print(error, file=sys.stderr)
        for duplicate in duplicates:
            print(f"skipped: {duplicate}", file=sys.stderr)
        if errors:
            return 1
        if duplicates and not writes:
            return 3
    return 0
