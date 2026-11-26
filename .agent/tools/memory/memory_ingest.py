#!/usr/bin/env python3
"""Ingesting external Markdown units: copy them in, never modifying their source directory.

An import is a copy with a stated provenance: `source_path` is rewritten to `import/<name>` so the
stored unit names where it came from, and the destination scope overrides whatever the file
claimed. A unit already stored with the same body is skipped, and so is a file whose rendered form
matches its target, which is what makes re-running an ingest a no-op instead of a second commit.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib.files import atomic_write
from memory_commit import (
    commit_external_changes,
    git_commit,
    restore_units,
    run_git,
)
from memory_frontmatter import parse_unit, render_unit
from memory_index import ensure_store, refresh, store_lock, write_indexes_for_scopes
from memory_inbox import imported_path
from memory_paths import MemoryStoreError, canonical_scope, repo_key, slug


def write_units(writes: list[tuple[Path, str]]) -> list[tuple[Path, str | None]]:
    """Commit, then write each rendered unit, and return each file's previous content.

    Every write happens inside one commit so a failure can restore each file from its backup,
    which is why the caller gets the backup list rather than a bare success flag.
    """
    backups: list[tuple[Path, str | None]] = []
    commit_external_changes()
    for path, rendered in writes:
        previous = path.read_text(encoding="utf-8") if path.exists() else None
        atomic_write(path, rendered)
        backups.append((path, previous))
    refreshed = refresh(write_indexes=False)
    backups.extend(write_indexes_for_scopes(refreshed))
    refreshed.close()
    run_git(["add", "-A"])
    return backups


def parse_imports(source: Path, destination_scope: str) -> tuple[list, list[str], list[str]]:
    """Parse the source units; returns the parsed pairs, the skipped names, and the errors."""
    parsed, errors, skipped = [], [], []
    for path in sorted(source.glob("*.md")):
        if path.name in {"MEMORY.md", "INDEX.md"}:
            skipped.append(path.name)
            continue
        try:
            unit = parse_unit(
                path, source_path=f"import/{path.name}", inferred_scope=destination_scope
            )
            unit["scope"] = destination_scope
            parsed.append((path, unit))
        except (OSError, ValueError) as error:
            errors.append(f"parse error: {path.name}: {error}")
    return parsed, skipped, errors


def ingest(args: argparse.Namespace) -> int:
    """Copy external Markdown units without ever modifying their source directory."""
    ensure_store()
    source = Path(args.path).expanduser()
    if not source.is_dir():
        print(f"source directory unavailable: {source}", file=sys.stderr)
        return 1
    destination_scope = canonical_scope(args.repo or repo_key())
    parsed, skipped, errors = parse_imports(source, destination_scope)
    for name in skipped:
        print(f"skipped: {name}")
    for error in errors:
        print(error, file=sys.stderr)
    if args.dry_run:
        for _, unit in parsed:
            print(unit["id"])
        return 0
    with store_lock():
        conn = refresh(write_indexes=False)
        existing = {
            row["id"]: row["body"] for row in conn.execute("SELECT id, body FROM units")
        }
        writes = []
        for _, unit in parsed:
            target = imported_path(unit)
            rendered = render_unit(unit)
            same_id = existing.get(unit["id"])
            if same_id is not None and same_id == unit["body"]:
                continue
            if target.exists() and target.read_text(encoding="utf-8") == rendered:
                continue
            writes.append((target, rendered))
        if not writes:
            print("no changes")
            return 0
        backups: list[tuple[Path, str | None]] = []
        try:
            backups = write_units(writes)
            git_commit(f"mem: ingest {args.source} {len(writes)} units")
        except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryStoreError) as error:
            restore_units(backups)
            print(str(error), file=sys.stderr)
            return 2
    for path, unit in parsed:
        if any(target.name.startswith(f"{unit['type']}_{slug(unit['title'])}") for target, _ in writes):
            print(unit["id"])
    return 0
