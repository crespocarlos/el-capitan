#!/usr/bin/env python3
"""Memory maintenance: init, reindex, doctor, stats, consolidate, ingest, and inbox import.

Store lifecycle and bulk operations that do not fit the unit or recall paths. Depends on
`store.py`, `units.py`, and `recall.py`.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from memory_store import (
    MemoryError,
    atomic_write,
    canonical_scope,
    commit_external_changes,
    duplicate_candidates,
    ensure_store,
    git_commit,
    initialize_database,
    memory_root,
    mutate,
    normalized,
    observation_directory,
    parse_unit,
    refresh,
    repo_key,
    run_git,
    scope_directory,
    slug,
    store_lock,
    tokens,
    write_indexes_for_scopes,
)
from memory_units import archive, render_unit
from memory_recall import is_stale


def init_store() -> int:
    root = memory_root()
    root.mkdir(parents=True, exist_ok=True)
    for directory in (root / "global", root / "repos", root / "observations", root / ".inbox"):
        directory.mkdir(exist_ok=True)
    ignore = root / ".gitignore"
    existing = ignore.read_text() if ignore.exists() else ""
    # `.sessions` holds raw tool telemetry; never commit it alongside approved units.
    additions = [line for line in (".index.sqlite", ".lock", ".sessions/")
                 if line not in existing.splitlines()]
    if additions:
        atomic_write(ignore, existing + ("" if not existing or existing.endswith("\n") else "\n")
                     + "\n".join(additions) + "\n")
    if not (root / ".git").exists():
        run_git(["init", "-q"])
    initialize_database()
    return 0


def reindex(args: argparse.Namespace) -> int:
    ensure_store()
    def change():
        return []
    code = mutate("mem: reindex", change)
    if code == 0:
        print("reindexed")
    return code


def doctor(args: argparse.Namespace) -> int:
    ensure_store()
    conn = refresh()
    result = conn.execute("SELECT count(*) FROM units").fetchone()[0]
    print(f"memory: healthy ({result} units)")
    return 0


def stats(args: argparse.Namespace) -> int:
    ensure_store()
    conn = refresh()
    total = conn.execute("SELECT count(*) FROM units").fetchone()[0]
    active = conn.execute("SELECT count(*) FROM units WHERE status = 'active'").fetchone()[0]
    print(json.dumps({"units": total, "active": active}, sort_keys=True))
    return 0


def duplicate_report(rows: list) -> list[str]:
    """The near-duplicate pairs in one scope and type, reported once per pair in row order."""
    report = []
    for index, row in enumerate(rows):
        unit = {"scope": row["scope"], "type": row["type"], "title": row["title"], "body": row["body"]}
        for other in rows[index + 1:]:
            candidate = {"scope": other["scope"], "type": other["type"], "title": other["title"], "body": other["body"]}
            left, right = set(tokens(unit["body"])), set(tokens(candidate["body"]))
            overlap = len(left & right) / len(left | right) if left or right else 0
            if (unit["scope"] == candidate["scope"] and unit["type"] == candidate["type"]
                    and (normalized(unit["title"]) == normalized(candidate["title"]) or overlap >= .6)):
                report.append(f"near-duplicate: {row['id']} {other['id']}")
    return report


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


def consolidate(args: argparse.Namespace) -> int:
    ensure_store()
    conn = refresh()
    report, archives = [], []
    rows = conn.execute(
        "SELECT * FROM units WHERE status = 'active' AND type != 'observation'"
    ).fetchall()
    for row in rows:
        paths = json.loads(row["paths"] or "[]")
        # Paths are relative to the unit's own repository, so they can only be checked
        # when this session is in that repository. Checking another repo's paths reports
        # every one of them as missing.
        if row["scope"] == repo_key():
            missing = [p for p in paths
                       if not any(token in p for token in "*?[") and not Path(p).exists()]
            if missing:
                report.append(f"missing path: {row['id']} ({', '.join(missing[:2])})")
        if is_stale(row["review_by"]) and row["uses"] == 0:
            report.append(f"archive: {row['id']}")
            archives.append(row["id"])
        if row["uses"] >= 5 and row["misled"] == 0:
            report.append(f"promote: {row['id']}")
    report.extend(duplicate_report(rows))
    for source in sorted((memory_root() / ".inbox").glob("*.md")):
        report.append(inbox_report(conn, source))
    print("\n".join(report) if report else "no proposals")
    if args.dry_run or not archives:
        return 0
    if input("Archive proposed units? [y/N] ").strip().lower() != "y":
        return 0
    for ident in archives:
        result = archive(argparse.Namespace(id=ident))
        if result:
            return result
    print(run_git(["diff", "--stat"], check=False).stdout, end="")
    return 0


def imported_path(unit: dict) -> Path:
    base = scope_directory(unit["scope"]) / f"{unit['type']}_{slug(unit['title'])}.md"
    if not base.exists():
        return base
    try:
        if parse_unit(base)["id"] == unit["id"]:
            return base
    except ValueError:
        pass
    return scope_directory(unit["scope"]) / f"{unit['type']}_{slug(unit['title'])}-{unit['id'][:8]}.md"


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


def restore_units(backups: list[tuple[Path, str | None]]) -> None:
    """Put every written unit back the way it was, deleting the ones that did not exist."""
    for path, previous in backups:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, previous)


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
        except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryError) as error:
            restore_units(backups)
            print(str(error), file=sys.stderr)
            return 2
    for path, unit in parsed:
        if any(target.name.startswith(f"{unit['type']}_{slug(unit['title'])}") for target, _ in writes):
            print(unit["id"])
    return 0


def gather_inbox(
    conn: sqlite3.Connection, sources: list[Path]
) -> tuple[list[tuple[Path, str]], list[Path], list[str], list[str]]:
    """Parse the chosen drafts; returns writes, removals, errors, and duplicate reports."""
    writes, removals, errors, duplicates = [], [], [], []
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
    return writes, removals, errors, duplicates


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
        writes, removals, errors, duplicates = gather_inbox(conn, sources)
        if writes:
            code = apply_inbox(writes, removals)
            if code:
                return code
        for path, _ in writes:
            print(path.stem)
        for error in errors:
            print(error, file=sys.stderr)
        for duplicate in duplicates:
            print(f"skipped: {duplicate}", file=sys.stderr)
        if errors:
            return 1
        if duplicates and not writes:
            return 3
    return 0
