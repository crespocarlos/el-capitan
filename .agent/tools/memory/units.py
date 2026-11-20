#!/usr/bin/env python3
"""Memory units: render, add, supersede, archive, cite, and read individual units.

The unit-level operations that write a file under the store, plus the two reads that print one
unit instead of a ranked result set. Imported by `recall.py` and `maintenance.py`; depends on
`store.py` only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import subprocess
import sys

from store import (
    TYPES,
    MemoryError,
    atomic_write,
    canonical_scope,
    commit_external_changes,
    duplicate_candidates,
    ensure_store,
    git_commit,
    mutate,
    observation_directory,
    parse_unit,
    refresh,
    run_git,
    scope_directory,
    slug,
    store_lock,
    today,
    unit_path,
    unit_row,
    write_indexes_for_scopes,
)


def render_unit(unit):
    def inline(values):
        return "[" + ", ".join(json.dumps(value) for value in values) + "]"
    extras = unit.get("extra_frontmatter") or []
    extra_block = ("\n" + "\n".join(extras)) if extras else ""
    return f"""---
id: {unit['id']}
type: {unit['type']}
scope: {'global' if unit['scope'] == 'global' else 'repo:' + unit['scope']}
title: {json.dumps(unit['title'])}
paths: {inline(unit['paths'])}
keywords: {inline(unit['keywords'])}
status: {unit['status']}
superseded_by: {unit['superseded_by'] or 'null'}
created: {unit['created']}
modified: {unit['modified']}
review_by: {unit['review_by'] or 'null'}
evidence: {inline(unit['evidence'])}
source_identity: {unit.get('source_identity') or 'null'}
uses: {unit['uses']}
last_used: {unit.get('last_used') or 'null'}
helped: {unit['helped']}
misled: {unit['misled']}{extra_block}
---
{unit['body']}"""


def update_frontmatter(path, changes):
    unit = parse_unit(path)
    unit.update(changes)
    unit["modified"] = today()
    previous = path.read_text(encoding="utf-8")
    atomic_write(path, render_unit(unit))
    return path, previous


def add(args):
    ensure_store()
    if args.type not in TYPES:
        print(f"invalid --type: {args.type}", file=sys.stderr)
        return 1
    body = sys.stdin.read()
    if not body.strip():
        print("add body must be supplied on stdin", file=sys.stderr)
        return 1
    scope = canonical_scope(args.scope)
    ident = f"{args.type}-{slug(args.title)}"
    unit = {
        "id": ident, "type": args.type, "scope": scope, "title": args.title,
        "paths": args.paths or [], "keywords": args.keywords or [], "status": "active",
        "superseded_by": None, "created": today(), "modified": today(),
        "review_by": (dt.date.today() + dt.timedelta(days={
            "feedback": 90, "project": 30, "reference": 180
        }.get(args.type, 120))).isoformat(),
        "evidence": args.evidence or [], "uses": 0, "last_used": None,
        "helped": 0, "misled": 0, "body": body if body.endswith("\n") else body + "\n",
    }
    with store_lock():
        conn = refresh(write_indexes=False)
        duplicates = duplicate_candidates(conn, unit)
        if duplicates and not args.force:
            print("\n".join(duplicates))
            return 3
        directory = observation_directory(scope) if args.type == "observation" else scope_directory(scope)
        path = directory / f"{args.type}_{slug(args.title)}.md"
        suffix = 2
        while path.exists() and not args.force:
            path = directory / f"{args.type}_{slug(args.title)}-{suffix}.md"
            suffix += 1
        if path.exists():
            if args.type == "observation":
                print("observations are immutable", file=sys.stderr)
                return 1
            unit["id"] = f"{ident}-{hashlib.sha1(unit['body'].encode()).hexdigest()[:8]}"
        previous = path.read_text(encoding="utf-8") if path.exists() else None
        def change():
            atomic_write(path, render_unit(unit))
            return [(path, previous)]
        try:
            commit_external_changes()
            backups = change()
            refreshed = refresh(write_indexes=False)
            backups.extend(write_indexes_for_scopes(refreshed))
            refreshed.close()
            run_git(["add", "-A"])
            git_commit(f"mem: add {unit['id']}")
        except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryError) as error:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, previous)
            print(str(error), file=sys.stderr)
            return 2
    print(unit["id"])
    return 0


def supersede(args):
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
        changed = update_frontmatter(path, {"status": "superseded", "superseded_by": args.new})
        return [changed]
    try:
        return mutate(f"mem: supersede {args.old}", change)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


def archive(args):
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


def cite(args):
    ensure_store()
    def change():
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
                updates = {
                    "uses": unit["uses"] + 1,
                    "last_used": today(),
                    args.outcome: unit[args.outcome] + 1,
                }
            backups.append(update_frontmatter(path, updates))
        return backups
    try:
        return mutate(f"mem: cite {','.join(args.ids)}", change)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


def listing(args):
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
    for row in rows:
        print(f"{row['id']}\t{row['type']}\t{row['scope']}\t{row['status']}\t{row['title']}")
    return 0


def show(args):
    ensure_store()
    conn = refresh()
    path = unit_path(conn, args.id)
    if not path:
        print("unknown id", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"), end="")
    return 0
