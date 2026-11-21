#!/usr/bin/env python3
"""Citing units: bumping the usage counters a later consolidation reads.

`used` is the generic signal and increments the usage counter alone; `helped` and `misled` are the
outcome counters the unit actually stores, so citing with either increments both the use and its
outcome. Observations are immutable — they are evidence, not guidance — so citing one is skipped
with a note naming where it belongs instead, rather than raising and discarding the other ids.
"""
from __future__ import annotations

import argparse
import sys

from memory_commit import mutate
from memory_frontmatter import parse_unit, update_frontmatter
from memory_index import ensure_store, refresh, unit_path, unit_row
from memory_paths import today


def cite(args: argparse.Namespace) -> int:
    """Increment the usage counters of each named unit, skipping immutable observations."""
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
