"""Unit writes: add a unit, cite units, supersede, archive, list and show.

An add creates a file: it picks the target, refuses a duplicate candidate unless `--force`, and
restores on a failed commit. Citing bumps `used`, and `helped`/`misled` with it; an observation is
evidence, so citing one is skipped with a note. The rest rewrite a stored unit or print units.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

from crew.lib.files import atomic_write
from crew.lib.output import json_payload, print_lines, rows_limit
from crew.memory.memory_frontmatter import TYPES, parse_unit, render_unit, update_frontmatter
from crew.memory.memory_paths import MemoryStoreError, canonical_scope, observation_directory, scope_directory, slug, today
from crew.memory.memory_store import (
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

EXIT_DUPLICATE = 3  # duplicate candidates found; nothing written (`--force` writes)


def new_unit(args: argparse.Namespace, scope: str, body: str) -> dict:
    """The unit an `add` writes, with the review date its type implies."""
    return {
        "id": f"{args.type}-{slug(args.title)}",
        "type": args.type,
        "scope": scope,
        "title": args.title,
        "paths": args.paths or [],
        "keywords": args.keywords or [],
        "status": "active",
        "superseded_by": None,
        "created": today(),
        "modified": today(),
        "review_by": (dt.date.today() + dt.timedelta(days={"feedback": 90, "project": 30, "reference": 180}.get(args.type, 120))).isoformat(),
        "evidence": args.evidence or [],
        "uses": 0,
        "last_used": None,
        "helped": 0,
        "misled": 0,
        "body": body if body.endswith("\n") else body + "\n",
    }


def free_path(scope: str, args: argparse.Namespace) -> tuple[Path, bool]:
    """The target path for a new unit, suffixed until it is free, and whether it already exists.

    The second value is true only under `--force`, where an existing file is overwritten rather
    than a new suffixed one chosen.
    """
    directory = observation_directory(scope) if args.type == "observation" else scope_directory(scope)
    path = directory / f"{args.type}_{slug(args.title)}.md"
    suffix = 2
    while path.exists() and not args.force:
        path = directory / f"{args.type}_{slug(args.title)}-{suffix}.md"
        suffix += 1
    return path, path.exists()


def write_new_unit(unit: dict, path: Path, previous: str | None) -> int:
    """Write the unit and commit it; 0, or 2 after restoring the file it replaced."""
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
        print(str(error), file=sys.stderr)
        return 2
    return 0


def add(args: argparse.Namespace) -> int:
    """Write one unit from stdin, refusing a duplicate candidate unless `--force`."""
    ensure_store()
    if args.type not in TYPES:
        print(f"invalid --type: {args.type}", file=sys.stderr)
        return 1
    body = sys.stdin.read()
    if not body.strip():
        print("add body must be supplied on stdin", file=sys.stderr)
        return 1
    scope = canonical_scope(args.scope)
    unit = new_unit(args, scope, body)
    with store_lock():
        conn = refresh(write_indexes=False)
        duplicates = duplicate_candidates(conn, unit)
        if duplicates and not args.force:
            print("\n".join(duplicates))
            return EXIT_DUPLICATE
        path, exists = free_path(scope, args)
        if exists:
            if args.type == "observation":
                print("observations are immutable", file=sys.stderr)
                return 1
            unit["id"] = f"{unit['id']}-{hashlib.sha1(unit['body'].encode()).hexdigest()[:8]}"
        previous = path.read_text(encoding="utf-8") if exists else None
        code = write_new_unit(unit, path, previous)
        if code:
            return code
    print(unit["id"])
    return 0


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
