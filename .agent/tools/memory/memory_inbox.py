"""Intake: the `.inbox` drafts and the ingest of external Markdown units.

`inbox_report` states what importing a draft would do (NOOP, UPDATE, SUPERSEDE, ADD) before any write;
`apply_inbox` imports it, removes the draft and restores every file on failure. An ingest copies units
in with `source_path: import/<name>` and the destination scope, skipping a body already stored, so a
re-run is a no-op; the source directory is never modified.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

from memory_frontmatter import parse_unit, render_unit
from memory_paths import MemoryStoreError, canonical_scope, memory_root, normalized, repo_key, scope_directory, slug
from memory_store import (
    commit_external_changes,
    duplicate_candidates,
    ensure_store,
    git_commit,
    refresh,
    restore_units,
    run_git,
    store_lock,
    write_indexes_for_scopes,
)

from lib.files import atomic_write

EXIT_DUPLICATE = 3  # every draft was a duplicate; nothing was imported


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
    except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryStoreError) as error:
        restore_units(backups)
        print(str(error), file=sys.stderr)
        return 2
    return 0


def import_inbox(args: argparse.Namespace) -> int:
    """Import the whole inbox or the named drafts, reporting each verdict.

    A bare call takes every draft, which is only safe when the inbox holds nothing from an earlier
    session. Naming the drafts is the explicit form and always allowed; a bulk import needs `--all`,
    and says how many it is about to take so a draft someone wrote weeks ago is never promoted by a
    command whose author only knew about their own.
    """
    ensure_store()
    inbox = memory_root() / ".inbox"
    wanted = set(args.files or [])
    sources = sorted(inbox.glob("*.md")) if args.all or not wanted else [
        inbox / name for name in wanted
    ]
    if not sources:
        print("no changes")
        return 0
    if not wanted and not args.all:
        print(f"error: a bare import would take all {len(sources)} draft(s) from {inbox}; name the "
              "files you approved, or pass --all to take the whole inbox deliberately",
              file=sys.stderr)
        for path in sources:
            print(f"  {path.name}", file=sys.stderr)
        return 2
    if args.all:
        print(f"importing all {len(sources)} draft(s) from {inbox}", file=sys.stderr)
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
            return EXIT_DUPLICATE
    return 0


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
    for _path, unit in parsed:
        if any(target.name.startswith(f"{unit['type']}_{slug(unit['title'])}") for target, _ in writes):
            print(unit["id"])
    return 0
