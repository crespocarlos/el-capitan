#!/usr/bin/env python3
"""Memory store façade: the one import site for the store's paths, format, index, and commit.

Split out of `crew-mem.py` so the CLI stays an argparse entry point, and later split again along
its own responsibilities: `memory_paths` holds the roots and scope rules, `memory_scalars` one
frontmatter value, `memory_frontmatter` the unit record, `memory_index` the database and its
refresh, and `memory_commit` the lock and the git commit. This module re-exports all of it, so the
modules above — units, recall, maintenance — keep one import site and never need to know which file
a name landed in.

The dependency order is paths -> scalars -> frontmatter -> index -> commit -> units -> search and
journal -> maintenance, so no module imports back into one that imports it.
"""
from __future__ import annotations

from lib.files import atomic_write
from memory_commit import (
    commit_external_changes,
    dirty_files,
    git_commit,
    mutate,
    run_git,
    unresolved_conflicts,
)
from memory_frontmatter import (
    EMITTED_KEYS,
    STATUSES,
    TYPES,
    parse_unit,
    render_unit,
    split_frontmatter,
)
from memory_index import (
    SCHEMA_VERSION,
    connection,
    ensure_store,
    initialize_database,
    refresh,
    store_lock,
    unit_path,
    unit_row,
    write_indexes_for_scopes,
)
from memory_paths import (
    MemoryStoreError,
    canonical_scope,
    database_path,
    journal_root,
    memory_root,
    normalized,
    observation_directory,
    repo_key,
    scope_directory,
    slug,
    source_files,
    today,
    tokens,
)
from memory_scalars import integer, list_value, parse_scalar, split_inline_list


def duplicate_candidates(conn, unit: dict) -> list[str]:
    """Ids of active units in the same scope and type whose title or body nearly matches."""
    candidates = conn.execute("""
        SELECT id, title, body FROM units
        WHERE scope = ? AND type = ? AND status = 'active'
    """, (unit["scope"], unit["type"])).fetchall()
    wanted = set(tokens(unit["body"]))
    matches = []
    for candidate in candidates:
        title_match = normalized(candidate["title"]) == normalized(unit["title"])
        existing = set(tokens(candidate["body"]))
        overlap = len(wanted & existing) / len(wanted | existing) if wanted or existing else 0
        if title_match or overlap >= 0.6:
            matches.append(candidate["id"])
    return matches
