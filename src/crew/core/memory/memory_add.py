"""Unit writes: add a unit, cite units, supersede, archive, list and show.

An add (`mem_write`) creates a file: it picks the target, refuses a duplicate candidate, and
restores on a failed commit. Citing bumps `used`, and `helped`/`misled` with it; an observation is
evidence, so citing one is skipped with a note. The rest rewrite a stored unit or print units.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from crew.core.memory.memory_frontmatter import TYPES, parse_unit, render_unit, update_frontmatter
from crew.core.memory.memory_paths import MemoryStoreError, canonical_scope, observation_directory, scope_directory, slug, today
from crew.core.memory.memory_store import (
    commit_external_changes,
    duplicate_candidates,
    ensure_store,
    git_commit,
    mutate,
    refresh,
    run_git,
    store_lock,
    unit_path,
    unit_row,
    write_indexes_for_scopes,
)
from crew.lib.errors import ToolError
from crew.lib.files import atomic_write
from crew.lib.output import json_payload, print_lines, rows_limit

EXIT_DUPLICATE = 3  # duplicate candidates found; nothing written


def new_unit(kind: str, title: str, scope: str, body: str, paths: list[str], keywords: list[str], evidence: list[str]) -> dict:
    """The unit `mem_write` writes, with the review date its type implies."""
    return {
        "id": f"{kind}-{slug(title)}",
        "type": kind,
        "scope": scope,
        "title": title,
        "paths": paths,
        "keywords": keywords,
        "status": "active",
        "superseded_by": None,
        "created": today(),
        "modified": today(),
        "review_by": (dt.date.today() + dt.timedelta(days={"feedback": 90, "project": 30, "reference": 180}.get(kind, 120))).isoformat(),
        "evidence": evidence,
        "uses": 0,
        "last_used": None,
        "helped": 0,
        "misled": 0,
        "body": body if body.endswith("\n") else body + "\n",
    }


def free_path(scope: str, kind: str, title: str) -> Path:
    """The target path for a new unit, suffixed until it is free."""
    directory = observation_directory(scope) if kind == "observation" else scope_directory(scope)
    path = directory / f"{kind}_{slug(title)}.md"
    suffix = 2
    while path.exists():
        path = directory / f"{kind}_{slug(title)}-{suffix}.md"
        suffix += 1
    return path


def write_new_unit(unit: dict, path: Path, previous: str | None) -> None:
    """Write the unit and commit it; on a failure, restore the file it replaced and raise ToolError."""
    try:
        commit_external_changes()
        atomic_write(path, render_unit(unit))
        backups = [(path, previous)]
        refreshed = refresh(write_indexes=False)
        backups.extend(write_indexes_for_scopes(refreshed))
        refreshed.close()
        run_git(["add", "-A"])
        git_commit(f"mem: add {unit['id']}")
    except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryStoreError) as error:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, previous)
        raise ToolError("memory", str(error), "commit", exit=2) from error


@dataclass
class Written:
    """The unit written: its id and file."""

    id: str
    path: str


def mem_write(
    type: str, scope: str, title: str, body: str, keywords: list[str] | None = None, paths: list[str] | None = None, evidence: list[str] | None = None
) -> Written:
    """Write one memory unit; a duplicate candidate refuses (exit 3) and names the units it repeats.

    Args:
        type: feedback, project, procedure, reference, failure-shield or observation
        scope: global, or the repository the unit is about
        title: one line naming the claim
        body: the unit's claim and its context
    """
    if type not in TYPES:
        raise ToolError("usage", f"invalid type: {type}", "type", f"choose from {', '.join(sorted(TYPES))}", 2)
    if not body.strip():
        raise ToolError("usage", "the body is empty", "body", "pass the unit's claim and context", 2)
    try:
        ensure_store()
        unit = new_unit(type, title, canonical_scope(scope), body, paths or [], keywords or [], evidence or [])
        with store_lock():
            duplicates = duplicate_candidates(refresh(write_indexes=False), unit)
            if duplicates:
                raise ToolError("refused", "duplicate of: " + "; ".join(duplicates), "duplicate", "cite or supersede the existing unit instead", EXIT_DUPLICATE)
            path = free_path(unit["scope"], type, title)
            write_new_unit(unit, path, None)
    except (MemoryStoreError, OSError, sqlite3.Error) as error:
        raise ToolError("memory", f"memory unavailable: {error}", "store", "set CREW_MEMORY_DIR to a writable store, or run install.sh", 2) from error
    return Written(unit["id"], str(path))


def cite(args: argparse.Namespace) -> int:
    """Increment the usage counters of each named unit, skipping immutable observations."""
    ensure_store()

    def change() -> list[tuple[Path, str | None]]:
        conn = refresh()
        paths = []
        for ident in args.ids:
            path = unit_path(conn, ident)
            if not path:
                raise ValueError(f"unknown id: {ident}")
            if unit_row(conn, ident)["type"] == "observation":
                print(f"skipped observation (immutable, cite in evidence): {ident}", file=sys.stderr)
                continue
            paths.append(path)
        backups = []
        for path in paths:
            unit = parse_unit(path)
            # `used` is the generic signal: it increments the usage counter. `helped`
            # and `misled` are counters the unit actually stores.
            if args.outcome == "used":
                updates = {"uses": unit["uses"] + 1, "last_used": today()}
            else:
                updates = {"uses": unit["uses"] + 1, "last_used": today(), args.outcome: unit[args.outcome] + 1}
            backups.append(update_frontmatter(path, updates))
        return backups

    try:
        return mutate(f"mem: cite {','.join(args.ids)}", change)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


def supersede(args: argparse.Namespace) -> int:
    """Mark one unit superseded by another, which must share its scope."""
    ensure_store()

    def change() -> list[tuple[Path, str | None]]:
        conn = refresh()
        old = unit_row(conn, args.old)
        new = unit_row(conn, args.new, old["scope"] if old else None)
        if not old or not new:
            raise ValueError("unknown id")
        if old["type"] == "observation" or new["type"] == "observation":
            raise ValueError("observations are immutable")
        if old["scope"] != new["scope"]:
            raise ValueError("superseded memories must share a scope")
        path = unit_path(conn, args.old)
        return [update_frontmatter(path, {"status": "superseded", "superseded_by": args.new})]

    try:
        return mutate(f"mem: supersede {args.old}", change)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


def archive(args: argparse.Namespace) -> int:
    """Archive one unit; observations are immutable and refused."""
    ensure_store()

    def change() -> list[tuple[Path, str | None]]:
        conn = refresh()
        path = unit_path(conn, args.id)
        if not path:
            raise ValueError("unknown id")
        if unit_row(conn, args.id)["type"] == "observation":
            raise ValueError("observations are immutable")
        return [update_frontmatter(path, {"status": "archived"})]

    try:
        return mutate(f"mem: archive {args.id}", change)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


def listing(args: argparse.Namespace) -> int:
    """Every unit, optionally narrowed by scope and status; `--json` for machines."""
    ensure_store()
    conn = refresh()
    clauses, values = [], []
    if args.scope:
        clauses.append("scope = ?")
        values.append(canonical_scope(args.scope))
    if args.status:
        clauses.append("status = ?")
        values.append(args.status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute("SELECT id, type, scope, status, title FROM units" + where + " ORDER BY id", values)
    entries = [dict(row) for row in rows]
    if args.json:
        print(json_payload(entries, args.limit, args.max_chars, what="memory units"))
        return 0
    printed, marker = rows_limit(entries, args.limit)
    lines = ["\t".join(str(entry[key]) for key in ("id", "type", "scope", "status", "title")) for entry in printed]
    if marker:
        lines.append(marker)
    print_lines(lines, args.max_chars, what="memory units", flag="--limit")
    return 0


def show(args: argparse.Namespace) -> int:
    """Print one stored unit exactly as it is on disk.

    The search covers the current repository's scope and global, which is where a unit named in a
    prompt usually lives. `--scope` reaches a unit filed under another repository, so an id printed
    by `import-inbox` is always reachable even when the draft named a different scope than this
    checkout resolves to.
    """
    ensure_store()
    conn = refresh()
    path = unit_path(conn, args.id, args.scope)
    if not path:
        print("unknown id", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"), end="")
    return 0
