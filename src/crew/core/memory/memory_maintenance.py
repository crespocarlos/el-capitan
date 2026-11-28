#!/usr/bin/env python3
"""Memory maintenance: init and consolidate.

Store lifecycle and the bulk report over the whole store. Inbox drafting and importing are
`memory_inbox`, and moving units between machines is `memory_transfer`, because each has its own
failure modes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crew.core.memory.memory_add import archive
from crew.core.memory.memory_inbox import inbox_report
from crew.core.memory.memory_paths import memory_root, normalized, repo_key, tokens
from crew.core.memory.memory_search import is_stale
from crew.core.memory.memory_store import ensure_store, initialize_database, refresh, run_git
from crew.lib.files import atomic_write


def init_store() -> int:
    """Create every store directory, the ignore file, and the index."""
    root = memory_root()
    root.mkdir(parents=True, exist_ok=True)
    for directory in (root / "global", root / "repos", root / "observations", root / ".inbox"):
        directory.mkdir(exist_ok=True)
    ignore = root / ".gitignore"
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    # `.sessions` holds raw tool telemetry; never commit it alongside approved units.
    additions = [line for line in (".index.sqlite", ".lock", ".sessions/") if line not in existing.splitlines()]
    if additions:
        atomic_write(ignore, existing + ("" if not existing or existing.endswith("\n") else "\n") + "\n".join(additions) + "\n")
    if not (root / ".git").exists():
        run_git(["init", "-q"])
    initialize_database()
    return 0


def duplicate_report(rows: list) -> list[str]:
    """The near-duplicate pairs in one scope and type, reported once per pair in row order."""
    report = []
    for index, row in enumerate(rows):
        unit = {"scope": row["scope"], "type": row["type"], "title": row["title"], "body": row["body"]}
        for other in rows[index + 1 :]:
            candidate = {"scope": other["scope"], "type": other["type"], "title": other["title"], "body": other["body"]}
            left, right = set(tokens(unit["body"])), set(tokens(candidate["body"]))
            overlap = len(left & right) / len(left | right) if left or right else 0
            if (
                unit["scope"] == candidate["scope"]
                and unit["type"] == candidate["type"]
                and (normalized(unit["title"]) == normalized(candidate["title"]) or overlap >= 0.6)
            ):
                report.append(f"near-duplicate: {row['id']} {other['id']}")
    return report


def consolidate(args: argparse.Namespace) -> int:
    """Report what consolidation would do, then archive the confirmed units."""
    ensure_store()
    conn = refresh()
    report, archives = [], []
    rows = conn.execute("SELECT * FROM units WHERE status = 'active' AND type != 'observation'").fetchall()
    for row in rows:
        paths = json.loads(row["paths"] or "[]")
        # Paths are relative to the unit's own repository, so they can only be checked
        # when this session is in that repository. Checking another repo's paths reports
        # every one of them as missing.
        if row["scope"] == repo_key():
            missing = [p for p in paths if not any(token in p for token in "*?[") and not Path(p).exists()]
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
