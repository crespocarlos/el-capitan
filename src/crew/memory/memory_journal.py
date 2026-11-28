"""The journal: month files read into immutable observations, imported, and single entries added.

An observation's id hashes its source and content, so a re-import or a second add of the same entry is
a no-op; a differing body under a known id is reported as a collision, never overwritten. Journal
source files are never written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from crew.lib.files import atomic_write
from crew.memory.memory_frontmatter import render_unit
from crew.memory.memory_paths import MemoryStoreError, canonical_scope, journal_root, observation_directory, slug, today
from crew.memory.memory_store import commit_external_changes, ensure_store, git_commit, refresh, run_git, store_lock


def journal_entries(path: Path) -> Iterator[dict]:
    """Yield one immutable observation record for every journal paragraph."""
    text = path.read_text(encoding="utf-8", errors="replace")
    for entry in re.split(r"(?m)^---\s*$", text):
        heading = re.search(r"(?m)^## (\d{4}-\d{2}-\d{2})\s+[—-]\s+(.+?)\s*$", entry)
        if not heading:
            continue
        entry_date, title = heading.groups()
        tags = re.search(r"(?mi)^\*\*Tags:\*\*\s*(.*?)\s*$", entry)
        repo = re.search(r"(?mi)^\*\*Repo:\*\*\s*(.*?)\s*$", entry)
        scope = canonical_scope(repo.group(1).strip()) if repo else "global"
        observation_directory(scope)  # reject unsafe scopes before any write
        keywords = re.findall(r"#([\w-]+)", tags.group(1)) if tags else []
        body = entry[heading.end() :]
        body = re.sub(r"(?mi)^\*\*(?:Tags|Repo):\*\*.*$\n?", "", body).strip()
        for paragraph_index, paragraph in enumerate(re.split(r"\n\s*\n", body), start=1):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            identity = f"{path.name}:{entry_date}:{slug(title)}:{paragraph_index}"
            content_hash = hashlib.sha256(paragraph.encode("utf-8")).hexdigest()
            ident = f"observation-{hashlib.sha256((identity + content_hash).encode()).hexdigest()[:16]}"
            yield {
                "id": ident,
                "type": "observation",
                "scope": scope,
                "title": title,
                "paths": [],
                "keywords": keywords,
                "status": "active",
                "superseded_by": None,
                "created": entry_date,
                "modified": entry_date,
                "review_by": None,
                "evidence": [],
                "uses": 0,
                "last_used": None,
                "helped": 0,
                "misled": 0,
                "body": paragraph + "\n",
                "source_identity": identity,
            }


def read_journal(root: Path) -> tuple[list[dict], list[str]]:
    """Every observation the journal files yield, plus one message per unreadable file."""
    parsed, errors = [], []
    for path in sorted(root.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].md")):
        try:
            parsed.extend(journal_entries(path))
        except OSError as error:
            errors.append(f"read error: {path.name}: {error}")
        except ValueError as error:
            errors.append(f"parse error: {path.name}: {error}")
    return parsed, errors


def pending_observations(conn: sqlite3.Connection, parsed: list[dict]) -> tuple[list[tuple[Path, str, str]], str]:
    """The observations not yet indexed, as `(target, rendered, id)`, or a collision message."""
    existing = {(row["id"], row["body"]): row["source_path"] for row in conn.execute("SELECT id, body, source_path FROM units WHERE type = 'observation'")}
    writes = []
    for unit in parsed:
        if (unit["id"], unit["body"]) in existing:
            continue
        target = observation_directory(unit["scope"]) / f"{unit['id']}.md"
        rendered = render_unit(unit)
        if target.exists():
            if target.read_text(encoding="utf-8") == rendered:
                continue
            return [], f"observation collision: {unit['id']}"
        writes.append((target, rendered, unit["id"]))
    return writes, ""


def restore_observations(backups: list[tuple[Path, str | None]]) -> None:
    """Put every written observation back, deleting the ones that did not exist."""
    for path, previous in backups:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, previous)


def write_observations(writes: list[tuple[Path, str, str]], message: str) -> int:
    """Write and commit the pending observations; 0, or 2 after restoring every file."""
    backups: list[tuple[Path, str | None]] = []
    try:
        commit_external_changes()
        for path, rendered, _ in writes:
            previous = path.read_text(encoding="utf-8") if path.exists() else None
            atomic_write(path, rendered)
            backups.append((path, previous))
        refreshed = refresh(write_indexes=False)
        refreshed.close()
        run_git(["add", "-A"])
        git_commit(message)
    except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryStoreError) as error:
        restore_observations(backups)
        print(str(error), file=sys.stderr)
        return 2
    return 0


def journal_import(args: argparse.Namespace) -> int:
    """Index journal evidence without changing any journal source file."""
    ensure_store()
    root = journal_root()
    if not root.is_dir():
        print(f"journal directory unavailable: {root}", file=sys.stderr)
        return 1
    parsed, errors = read_journal(root)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 2
    with store_lock():
        conn = refresh(write_indexes=False)
        writes, collision = pending_observations(conn, parsed)
        if collision:
            print(collision, file=sys.stderr)
            return 2
        if args.dry_run:
            for _, _, ident in writes:
                print(ident)
            return 0
        if not writes:
            print("no changes")
            return 0
        code = write_observations(writes, f"mem: journal import {len(writes)} observations")
        if code:
            return code
    for _, _, ident in writes:
        print(ident)
    return 0


def observation_unit(ident: str, args: argparse.Namespace, scope: str, entry_date: str, body: str) -> dict:
    """The unit a `journal add` writes: one immutable observation with a deterministic identity."""
    return {
        "id": ident,
        "type": "observation",
        "scope": scope,
        "title": args.title,
        "paths": [],
        "keywords": [tag.removeprefix("#") for tag in args.tags],
        "status": "active",
        "superseded_by": None,
        "created": entry_date,
        "modified": entry_date,
        "review_by": None,
        "evidence": [],
        "uses": 0,
        "last_used": None,
        "helped": 0,
        "misled": 0,
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
    identity = json.dumps({"scope": scope, "date": entry_date, "title": args.title, "tags": keywords, "body": body}, sort_keys=True, separators=(",", ":"))
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
