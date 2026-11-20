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

from store import (
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
from units import archive, render_unit
from recall import is_stale


def init_store():
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


def reindex(args):
    ensure_store()
    def change():
        return []
    code = mutate("mem: reindex", change)
    if code == 0:
        print("reindexed")
    return code


def doctor(args):
    ensure_store()
    conn = refresh()
    result = conn.execute("SELECT count(*) FROM units").fetchone()[0]
    print(f"memory: healthy ({result} units)")
    return 0


def stats(args):
    ensure_store()
    conn = refresh()
    total = conn.execute("SELECT count(*) FROM units").fetchone()[0]
    active = conn.execute("SELECT count(*) FROM units WHERE status = 'active'").fetchone()[0]
    print(json.dumps({"units": total, "active": active}, sort_keys=True))
    return 0


def consolidate(args):
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
        current = repo_key()
        if row["scope"] == current:
            missing = [p for p in paths
                       if not any(token in p for token in "*?[") and not Path(p).exists()]
            if missing:
                report.append(f"missing path: {row['id']} ({', '.join(missing[:2])})")
        if is_stale(row["review_by"]) and row["uses"] == 0:
            report.append(f"archive: {row['id']}")
            archives.append(row["id"])
        if row["uses"] >= 5 and row["misled"] == 0:
            report.append(f"promote: {row['id']}")
    for index, row in enumerate(rows):
        unit = {"scope": row["scope"], "type": row["type"], "title": row["title"], "body": row["body"]}
        for other in rows[index + 1:]:
            candidate = {"scope": other["scope"], "type": other["type"], "title": other["title"], "body": other["body"]}
            left, right = set(tokens(unit["body"])), set(tokens(candidate["body"]))
            overlap = len(left & right) / len(left | right) if left or right else 0
            if (unit["scope"] == candidate["scope"] and unit["type"] == candidate["type"]
                    and (normalized(unit["title"]) == normalized(candidate["title"]) or overlap >= .6)):
                report.append(f"near-duplicate: {row['id']} {other['id']}")
    for source in sorted((memory_root() / ".inbox").glob("*.md")):
        try:
            candidate = parse_unit(source, inferred_scope=repo_key())
        except (OSError, ValueError) as error:
            report.append(f"inbox error: {source.name}: {error}")
            continue
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
            report.append(f"NOOP inbox: {source.name} matches {exact['id']}")
        elif same_title:
            report.append(f"UPDATE inbox: {source.name} replaces {same_title['id']}")
        elif overlap:
            report.append(f"SUPERSEDE inbox: {source.name} overlaps {' '.join(overlap)}")
        else:
            report.append(f"ADD inbox: {source.name}")
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


def imported_path(unit):
    base = scope_directory(unit["scope"]) / f"{unit['type']}_{slug(unit['title'])}.md"
    if not base.exists():
        return base
    try:
        if parse_unit(base)["id"] == unit["id"]:
            return base
    except ValueError:
        pass
    return scope_directory(unit["scope"]) / f"{unit['type']}_{slug(unit['title'])}-{unit['id'][:8]}.md"


def ingest(args):
    """Copy external Markdown units without ever modifying their source directory."""
    ensure_store()
    source = Path(args.path).expanduser()
    if not source.is_dir():
        print(f"source directory unavailable: {source}", file=sys.stderr)
        return 1
    destination_scope = canonical_scope(args.repo or repo_key())
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
        backups = []
        try:
            commit_external_changes()
            for path, rendered in writes:
                previous = path.read_text(encoding="utf-8") if path.exists() else None
                atomic_write(path, rendered)
                backups.append((path, previous))
            refreshed = refresh(write_indexes=False)
            backups.extend(write_indexes_for_scopes(refreshed))
            refreshed.close()
            run_git(["add", "-A"])
            git_commit(f"mem: ingest {args.source} {len(writes)} units")
        except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryError) as error:
            for path, previous in backups:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, previous)
            print(str(error), file=sys.stderr)
            return 2
    for path, unit in parsed:
        if any(target.name.startswith(f"{unit['type']}_{slug(unit['title'])}") for target, _ in writes):
            print(unit["id"])
    return 0


def import_inbox(args):
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
        writes, removals, backups = [], [], []
        errors, duplicates = [], []
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
        if writes:
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
                for path, previous in backups:
                    if previous is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, previous)
                print(str(error), file=sys.stderr)
                return 2
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
