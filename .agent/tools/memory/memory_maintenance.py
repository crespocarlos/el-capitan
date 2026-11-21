#!/usr/bin/env python3
"""Memory maintenance: init, reindex, doctor, stats, and consolidate.

Store lifecycle and the bulk operations that report on the whole store. Ingesting external
Markdown is `memory_ingest`, and inbox drafting and importing is `memory_inbox`, because each has
its own failure modes; both are re-exported here so `crew-mem.py` keeps one import site.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from lib.files import atomic_write
from memory_commit import mutate, run_git
from memory_context import is_stale
from memory_frontmatter import render_unit
from memory_index import (
    ensure_store,
    initialize_database,
    refresh,
    write_indexes_for_scopes,
)
from memory_paths import memory_root, normalized, repo_key, tokens
from memory_units import archive
from memory_ingest import ingest, parse_imports, write_units  # noqa: F401 — re-exported
from memory_inbox import import_inbox, imported_path, inbox_report  # noqa: F401 — re-exported


def init_store() -> int:
    """Create every store directory, the ignore file, and the index."""
    root = memory_root()
    root.mkdir(parents=True, exist_ok=True)
    for directory in (root / "global", root / "repos", root / "observations", root / ".inbox"):
        directory.mkdir(exist_ok=True)
    ignore = root / ".gitignore"
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
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


def consolidate(args: argparse.Namespace) -> int:
    """Report what consolidation would do, then archive the confirmed units."""
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
