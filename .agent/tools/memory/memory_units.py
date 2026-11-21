#!/usr/bin/env python3
"""Memory units: supersede, archive, list, and show a unit.

The unit-level operations that rewrite a stored file or read one back, plus the two reads that
print units instead of a ranked result set. Adding a unit and citing one are `memory_add` and
`memory_cite`; both are re-exported here so `crew-mem.py` keeps one import site.
"""
from __future__ import annotations

import argparse
import sys

from lib.output import json_payload, print_lines, rows_limit
from memory_commit import mutate
from memory_frontmatter import update_frontmatter
from memory_index import ensure_store, refresh, unit_path, unit_row
from memory_paths import canonical_scope
from memory_add import add, free_path, new_unit, write_new_unit  # noqa: F401 — re-exported
from memory_cite import cite  # noqa: F401 — re-exported


def supersede(args: argparse.Namespace) -> int:
    """Mark one unit superseded by another, which must share its scope."""
    ensure_store()

    def change():
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

    def change():
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
    lines = ["\t".join(str(entry[key]) for key in ("id", "type", "scope", "status", "title"))
             for entry in printed]
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
