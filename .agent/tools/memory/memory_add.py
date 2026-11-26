#!/usr/bin/env python3
"""Adding a unit: choose the target file, write it, index it, and commit it.

An add is the one unit write that creates a file rather than rewriting one, so the questions it
answers are its own: where the file goes, whether that name is taken, and what to restore when the
commit fails. A duplicate candidate refuses the add unless `--force` says otherwise, because two
units with the same claim split the guidance a later recall reads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib.files import atomic_write
from memory_commit import commit_external_changes, git_commit, run_git
from memory_frontmatter import TYPES, render_unit
from memory_index import ensure_store, refresh, store_lock, write_indexes_for_scopes
from memory_paths import (
    MemoryStoreError,
    canonical_scope,
    observation_directory,
    scope_directory,
    slug,
    today,
)
from memory_store import duplicate_candidates


def new_unit(args: argparse.Namespace, scope: str, body: str) -> dict:
    """The unit an `add` writes, with the review date its type implies."""
    return {
        "id": f"{args.type}-{slug(args.title)}", "type": args.type, "scope": scope,
        "title": args.title,
        "paths": args.paths or [], "keywords": args.keywords or [], "status": "active",
        "superseded_by": None, "created": today(), "modified": today(),
        "review_by": (dt.date.today() + dt.timedelta(days={
            "feedback": 90, "project": 30, "reference": 180
        }.get(args.type, 120))).isoformat(),
        "evidence": args.evidence or [], "uses": 0, "last_used": None,
        "helped": 0, "misled": 0, "body": body if body.endswith("\n") else body + "\n",
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
            return 3
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
