#!/usr/bin/env python3
"""Adding one journal entry straight to the store, as a single immutable observation.

The identity is a hash of the entry's own content, so the same entry added twice lands on the same
path: an identical copy is a no-op, and a different body under that id is a collision, reported
rather than overwritten. A journal source file is never written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys

from memory_frontmatter import render_unit
from memory_index import ensure_store, store_lock
from memory_journal import write_observations
from memory_paths import canonical_scope, observation_directory, today


def observation_unit(ident: str, args: argparse.Namespace, scope: str, entry_date: str,
                     body: str) -> dict:
    """The unit a `journal add` writes: one immutable observation with a deterministic identity."""
    return {
        "id": ident, "type": "observation", "scope": scope, "title": args.title,
        "paths": [], "keywords": [tag.removeprefix("#") for tag in args.tags], "status": "active",
        "superseded_by": None, "created": entry_date, "modified": entry_date,
        "review_by": None, "evidence": [], "uses": 0, "last_used": None,
        "helped": 0, "misled": 0,
        "body": body if body.endswith("\n") else body + "\n",
        "source_identity": f"journal-add:{ident}",
    }


def journal_add(args: argparse.Namespace) -> int:
    """Store a new journal entry directly as one immutable observation."""
    ensure_store()
    body = sys.stdin.read()
    if not body.strip():
        print("journal add body must be supplied on stdin", file=sys.stderr)
        return 1
    entry_date = args.date or today()
    try:
        dt.date.fromisoformat(entry_date)
    except ValueError:
        print(f"invalid --date: {entry_date}", file=sys.stderr)
        return 1
    scope = canonical_scope(args.repo) if args.repo else "global"
    try:
        observation_directory(scope)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    keywords = [tag.removeprefix("#") for tag in args.tags]
    identity = json.dumps(
        {"scope": scope, "date": entry_date, "title": args.title, "tags": keywords, "body": body},
        sort_keys=True, separators=(",", ":"),
    )
    ident = f"observation-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    unit = observation_unit(ident, args, scope, entry_date, body)
    path = observation_directory(scope) / f"{ident}.md"
    rendered = render_unit(unit)
    with store_lock():
        if path.exists():
            if path.read_text(encoding="utf-8") != rendered:
                print(f"observation collision: {ident}", file=sys.stderr)
                return 2
            print(ident)
            return 0
        code = write_observations([(path, rendered, ident)], f"mem: journal add {ident}")
        if code:
            return code
    print(ident)
    return 0
