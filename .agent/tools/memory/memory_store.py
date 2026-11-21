#!/usr/bin/env python3
"""Memory store: paths, database, frontmatter parsing, indexing, and locking.

Split out of `crew-mem.py` so the CLI stays an argparse entry point. Everything here is
imported by `units.py`, `recall.py`, and `maintenance.py`; nothing here parses arguments or
prints a command result. The dependency order is store -> units -> recall -> maintenance, so
no module has to import back into one that imports it.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from lib.files import atomic_write
from lib.git import GitError, conflicted_paths, dirty_files as _dirty_files, run_git as _run_git

TYPES = {
    "user", "feedback", "project", "reference", "failure-shield", "procedure",
    "observation",
}
STATUSES = {"active", "superseded", "archived"}


class MemoryError(Exception):
    """Expected unavailable/corrupt-store error."""


def memory_root() -> Path:
    return Path(os.environ.get("CREW_MEMORY_DIR", Path.home() / ".agent" / "memory"))


def journal_root() -> Path:
    return Path(os.environ.get("CREW_JOURNAL_DIR", Path.home() / ".agent" / "journal"))


def database_path() -> Path:
    return memory_root() / ".index.sqlite"


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "memory"


def today() -> str:
    return dt.date.today().isoformat()


def repo_key() -> str:
    """The repository scope: the upstream (or origin) repository's bare name, else the directory."""
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True,
            check=True
        ).stdout.strip()
        remotes = subprocess.run(
            ["git", "-C", top, "remote"], text=True, capture_output=True,
            check=True
        ).stdout.splitlines()
        for remote_name in ["upstream", "origin", *remotes]:
            remote = subprocess.run(
                ["git", "-C", top, "remote", "get-url", remote_name], text=True,
                capture_output=True,
            )
            if remote.returncode:
                continue
            match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", remote.stdout.strip())
            if match:
                return match.group(2)
        return Path(top).name
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd().name


def canonical_scope(value: str) -> str:
    if value == "global":
        return "global"
    value = value.removeprefix("repo:")
    owner_repo = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/([A-Za-z0-9._-]+?)(?:\.git)?", value)
    return owner_repo.group(1) if owner_repo else value


def scope_directory(scope: str) -> Path:
    scope = canonical_scope(scope)
    return memory_root() / ("global" if scope == "global" else f"repos/{scope}")


def observation_directory(scope: str) -> Path:
    scope = canonical_scope(scope)
    if scope in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", scope):
        raise ValueError(f"invalid observation scope: {scope!r}")
    return memory_root() / "observations" / scope


def ensure_store() -> None:
    if not database_path().exists():
        raise MemoryError("memory store missing; run crew-mem.py init")


def connection() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(database_path())
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT count(*) FROM units")
        return conn
    except sqlite3.Error as error:
        raise MemoryError(f"memory store unreadable or corrupt: {error}") from error


SCHEMA_VERSION = 1


def initialize_database() -> None:
    conn = sqlite3.connect(database_path())
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.Error:
        version = 0
    if version not in (0, SCHEMA_VERSION):
        # The index is a rebuildable cache: drop it and let refresh() repopulate.
        conn.execute("DROP TABLE IF EXISTS units")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS units USING fts5(
            id UNINDEXED, type UNINDEXED, scope UNINDEXED, title,
            body, keywords UNINDEXED, paths UNINDEXED, status UNINDEXED,
            review_by UNINDEXED, source_path UNINDEXED, mtime UNINDEXED,
            size UNINDEXED, created UNINDEXED, uses UNINDEXED, helped UNINDEXED,
            misled UNINDEXED, tokenize='porter unicode61'
        )
    """)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.close()


@contextmanager
def store_lock() -> Iterator[None]:
    # Binary mode: this file only carries an flock, and a text open would need an encoding it never uses.
    lock = (memory_root() / ".lock").open("a+b")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def split_inline_list(inner: str) -> list[str]:
    """Split an inline list body on commas that sit outside quotes."""
    parts, current, quote, index = [], [], None, 0
    while index < len(inner):
        char = inner[index]
        if quote:
            if char == "\\" and index + 1 < len(inner):
                current.append(inner[index:index + 2])
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == ",":
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def parse_scalar(value: str) -> object:
    value = value.strip()
    if value in {"null", "None", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [part.strip("'\"") for part in split_inline_list(inner)]
    if value[:1] in {'"', "'"}:
        # render_unit writes scalars with json.dumps, so unescape must be its inverse;
        # plain strip() re-escapes backslashes on every rewrite.
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            # Not JSON: single-quoted YAML escapes an inner quote by doubling it.
            if value[0] == "'" and value.endswith("'"):
                return value[1:-1].replace("''", "'")
            return value.strip("'\"")
        return parsed if isinstance(parsed, str) else value.strip("'\"")
    return value


EMITTED_KEYS = {
    "id", "type", "scope", "title", "paths", "keywords", "status", "superseded_by",
    "created", "modified", "review_by", "evidence", "source_identity", "uses",
    "last_used", "helped", "misled",
}
# `name` and `description` are consumed as id/title only when the canonical key is absent;
# otherwise they are preserved like any other unmodeled key. See split_frontmatter.


def split_frontmatter(text: str, path: Path) -> tuple[list[str], list[str], str]:
    """Return (frontmatter lines, extra raw lines, body).

    Aliases (`name`, `description`) are only consumed when the canonical key is absent;
    otherwise the original line is preserved, so a hand-authored unit round-trips intact.
    """
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError(f"unterminated YAML frontmatter: {path}")
    lines = text[4:end].splitlines()
    top_level = {match.group(1) for line in lines
                 if (match := re.match(r"^([\w-]+):", line))}
    consumed = set(EMITTED_KEYS)
    if "title" not in top_level:
        consumed.add("description")
    if "id" not in top_level:
        consumed.add("name")
    extras, keeping = [], False
    block_indent = 0
    for line in lines:
        match = re.match(r"^(\s*)([\w-]+):", line)
        if match:
            indent, key = match.groups()
            keeping = key not in consumed
            # Children of a preserved block key stay preserved, blank lines included.
            block_indent = len(indent)
        elif not line.strip():
            # A blank line ends only a top-level key's block, not a nested one.
            keeping = keeping and block_indent > 0
        if keeping:
            extras.append(line)
    return lines, extras, text[end + 4:].lstrip("\n")


def parse_unit(
    path: Path, source_path: str | None = None, inferred_scope: str | None = None
) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    lines, extras, body = split_frontmatter(text, path)
    data, metadata, in_metadata = {}, {}, False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.strip() == "metadata:":
            in_metadata = True
            continue
        match = re.match(r"^(\s*)([\w-]+):\s*(.*)$", line)
        if not match:
            continue
        indent, key, value = match.groups()
        target = metadata if in_metadata and indent else data
        target[key] = parse_scalar(value)
        if not indent:
            in_metadata = False
    unit_type = data.get("type") or metadata.get("type")
    ident = data.get("id") or data.get("name")
    if not unit_type or not ident:
        raise ValueError("frontmatter requires id/name and type/metadata.type")
    if unit_type not in TYPES:
        raise ValueError(f"unknown memory type: {unit_type}")
    scope = canonical_scope(data.get("scope") or inferred_scope or _scope_from_path(path))
    title = data.get("title") or data.get("description") or path.stem.replace("_", " ")
    stat = data.get("status", "active")
    if stat not in STATUSES:
        raise ValueError(f"invalid status: {stat}")
    claim = next((line.strip() for line in body.splitlines() if line.strip()), title)
    file_stat = path.stat()
    return {
        "id": str(ident), "type": str(unit_type), "scope": scope, "title": str(title),
        "body": body, "claim": claim, "keywords": list_value(data.get("keywords")),
        "paths": list_value(data.get("paths")), "status": stat,
        "superseded_by": data.get("superseded_by"), "review_by": data.get("review_by"),
        "created": data.get("created") or data.get("modified") or today(),
        "modified": data.get("modified") or metadata.get("modified") or today(),
        "evidence": list_value(data.get("evidence")), "uses": integer(data.get("uses")),
        "helped": integer(data.get("helped")), "misled": integer(data.get("misled")),
        "last_used": data.get("last_used"),
        "source_identity": data.get("source_identity"),
        "source_path": source_path or str(path.relative_to(memory_root())),
        "mtime": file_stat.st_mtime_ns, "size": file_stat.st_size,
        "extra_frontmatter": extras,
    }


def list_value(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def integer(value: object) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _scope_from_path(path: Path) -> str:
    relative = path.relative_to(memory_root())
    if relative.parts[0] == "global":
        return "global"
    if len(relative.parts) >= 2 and relative.parts[0] == "repos":
        return relative.parts[1]
    if len(relative.parts) >= 2 and relative.parts[0] == "observations":
        return relative.parts[1]
    return repo_key()


def source_files() -> Iterator[Path]:
    root = memory_root()
    for directory in [
        root / "global", *(root / "repos").glob("*"), *(root / "observations").glob("*")
    ]:
        if directory.is_dir():
            yield from sorted(
                file for file in directory.glob("*.md")
                if file.name not in {"INDEX.md", "MEMORY.md"}
            )


def refresh(write_indexes: bool = True) -> sqlite3.Connection:
    """Synchronize changed external units using persisted mtime/size fingerprints."""
    conn = connection()
    indexed = {row["source_path"]: row for row in conn.execute(
        "SELECT id, source_path, mtime, size FROM units"
    )}
    current = set()
    for path in source_files():
        relative = str(path.relative_to(memory_root()))
        current.add(relative)
        stat = path.stat()
        previous = indexed.get(relative)
        if previous and previous["mtime"] == stat.st_mtime_ns and previous["size"] == stat.st_size:
            continue
        conn.execute("DELETE FROM units WHERE source_path = ?", (relative,))
        unit = parse_unit(path)
        conn.execute("""
            INSERT INTO units VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            unit["id"], unit["type"], unit["scope"], unit["title"], unit["body"],
            json.dumps(unit["keywords"]), json.dumps(unit["paths"]), unit["status"],
            unit["review_by"], unit["source_path"], unit["mtime"], unit["size"],
            unit["created"], unit["uses"], unit["helped"], unit["misled"],
        ))
    for relative in set(indexed) - current:
        conn.execute("DELETE FROM units WHERE source_path = ?", (relative,))
    conn.commit()
    if write_indexes:
        write_indexes_for_scopes(conn)
    return conn


def write_indexes_for_scopes(conn: sqlite3.Connection) -> list[tuple[Path, str | None]]:
    scopes = {"global"}
    scopes.update(row[0] for row in conn.execute("SELECT DISTINCT scope FROM units"))
    scopes.update(directory.name for directory in (memory_root() / "repos").glob("*") if directory.is_dir())
    backups = []
    for scope in scopes:
        directory = scope_directory(scope)
        if not directory.exists():
            continue
        rows = conn.execute("""
            SELECT id, type, title FROM units
            WHERE scope = ? AND status = 'active' AND type != 'observation' ORDER BY id
        """, (scope,)).fetchall()
        content = "".join(f"{row['id']} ({row['type']}): {row['title']}\n" for row in rows)
        path = directory / "INDEX.md"
        previous = path.read_text(encoding="utf-8") if path.exists() else None
        if previous != content:
            atomic_write(path, content)
            backups.append((path, previous))
    return backups


def unit_row(conn: sqlite3.Connection, ident: str, scope: str | None = None) -> sqlite3.Row | None:
    """Resolve IDs in the current repository scope before falling back to global."""
    scopes = [canonical_scope(scope)] if scope else [repo_key(), "global"]
    for candidate_scope in scopes:
        row = conn.execute(
            "SELECT * FROM units WHERE id = ? AND scope = ? ORDER BY source_path",
            (ident, candidate_scope),
        ).fetchone()
        if row:
            return row
    return None


def unit_path(conn: sqlite3.Connection, ident: str, scope: str | None = None) -> Path | None:
    row = unit_row(conn, ident, scope)
    return memory_root() / row["source_path"] if row else None


def run_git(arguments: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Git against the memory store, whose repository is not the caller's working directory."""
    return _run_git(memory_root(), list(arguments), check=check)


def dirty_files() -> list[str]:
    return _dirty_files(memory_root())


def unresolved_conflicts() -> list[str]:
    """Return conflicted paths, or raise when git cannot answer.

    A failed `git diff` (broken index, missing repo, held lock) is not "no conflicts":
    reporting clean would let `commit_external_changes` adopt conflict markers.
    """
    try:
        return conflicted_paths(memory_root())
    except GitError as error:
        raise MemoryError("cannot verify the memory store's merge state: " + str(error)) from error


def git_commit(message: str) -> None:
    result = run_git([
        "-c", "user.name=mem", "-c", "user.email=mem@localhost",
        "commit", "-m", message
    ], check=False)
    if result.returncode:
        raise MemoryError(f"git commit failed: {result.stderr.strip() or result.stdout.strip()}")


def commit_external_changes() -> None:
    # `git add -A` on a conflicted file marks the working tree (markers included) as the
    # resolution, so a merge conflict would be silently adopted and indexed.
    conflicts = unresolved_conflicts()
    if conflicts:
        raise MemoryError(
            "memory store has unresolved merge conflicts: " + ", ".join(conflicts)
            + " — resolve them in " + str(memory_root()) + " and retry"
        )
    changes = dirty_files()
    if changes:
        run_git(["add", "-A"])
        git_commit(f"mem: external {len(changes)} files")


def mutate(operation: str, change: Callable[[], list[tuple[Path, str | None]]]) -> int:
    """Lock, preserve changed unit files, index, commit, and restore on failure."""
    ensure_store()
    with store_lock():
        try:
            commit_external_changes()
            backups = change()
            conn = refresh(write_indexes=False)
            backups.extend(write_indexes_for_scopes(conn))
            conn.close()
            run_git(["add", "-A"])
            if run_git(["diff", "--cached", "--quiet"], check=False).returncode:
                git_commit(operation)
            return 0
        except (OSError, sqlite3.Error, subprocess.SubprocessError, MemoryError) as error:
            for path, old_content in locals().get("backups", []):
                if old_content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, old_content)
            print(str(error), file=sys.stderr)
            return 2


def duplicate_candidates(conn: sqlite3.Connection, unit: dict) -> list[str]:
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


def tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", value.lower())
