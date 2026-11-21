#!/usr/bin/env python3
"""Memory search: the FTS query, the scope filter, and the `search` command's output.

The index is FTS5, whose query language treats `(`, `:` and quotes as operators, so a raw model- or
user-written query can raise instead of matching; `fts_rows` retries it as a quoted-phrase OR before
giving up. Scope defaults to this repository plus global, because an unscoped search returns other
projects' units into this codebase's guidance.
"""
from __future__ import annotations

import argparse
import re
import sqlite3

from lib.output import json_payload, print_lines, rows_limit
from memory_index import ensure_store, refresh
from memory_paths import canonical_scope, repo_key


def sanitized_query(query: str) -> str:
    """Quoted-phrase fallback: FTS5 treats `(`, `:` and quotes as operators."""
    terms = [term for term in re.split(r"[^\w]+", query) if term]
    return " OR ".join(f'"{term}"' for term in terms) if terms else ""


def fts_rows(
    conn: sqlite3.Connection, query: str, scopes: list[str] | None,
    types: list[str] | None = None, include_observations: bool = False,
) -> list[sqlite3.Row]:
    clauses, values = ["status = 'active'"], []
    if not include_observations and "observation" not in (types or []):
        clauses.append("type != 'observation'")
    if scopes:
        clauses.append("scope IN (" + ",".join("?" for _ in scopes) + ")")
        values.extend(scopes)
    if types:
        clauses.append("type IN (" + ",".join("?" for _ in types) + ")")
        values.extend(types)
    if query.strip():
        statement = (
            "SELECT *, bm25(units) AS rank FROM units WHERE units MATCH ? AND "
            + " AND ".join(clauses) + " ORDER BY rank"
        )
        try:
            return conn.execute(statement, [query, *values]).fetchall()
        except sqlite3.OperationalError:
            fallback = sanitized_query(query)
            if not fallback:
                return []
            try:
                return conn.execute(statement, [fallback, *values]).fetchall()
            except sqlite3.OperationalError:
                return []
    return conn.execute("SELECT *, 0 AS rank FROM units WHERE " + " AND ".join(clauses), values).fetchall()


def selected_scopes(repo: str | None) -> list[str]:
    """The scopes a query covers: one named repository plus global, else this repository."""
    if repo and repo != "*":
        return ["global", canonical_scope(repo)]
    return ["global", repo_key()]


def search(args: argparse.Namespace) -> int:
    ensure_store()
    conn = refresh()
    # Scope to this repository plus global by default: an unscoped search returns other
    # projects' units into this codebase's guidance. --repo '*' searches everything.
    scopes = None if args.repo == "*" else selected_scopes(args.repo)
    rows = fts_rows(
        conn, args.query, scopes, [args.type] if args.type else None,
        include_observations=True,
    )[:args.top]
    entries = [dict(row) for row in rows]
    if args.json:
        print(json_payload(entries, args.limit, args.max_chars, what="memory units"))
    else:
        printed, marker = rows_limit(entries, args.limit)
        lines = [entry["id"] for entry in printed]
        if marker:
            lines.append(marker)
        print_lines(lines, args.max_chars, what="memory ids", flag="--limit")
    return 0
