#!/usr/bin/env python3
"""Moving units between machines: `export` to a private `.tar.gz`, `import` into an existing store.

An export carries regular unit files only (no index, inbox, sessions, links or hidden files). An
import checks every member before it writes one: the path layout, size caps, frontmatter, type,
status, that the declared scope is the path's, and that no id or case-folded name collides. It never
overwrites a stored unit; a write that fails partway is undone by `mutate`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import BinaryIO

from crew.core.memory.memory_frontmatter import parse_unit
from crew.core.memory.memory_paths import MemoryStoreError, canonical_scope, memory_root, source_files
from crew.core.memory.memory_store import ensure_store, mutate, refresh, store_lock
from crew.lib.files import atomic_write

# The only paths an archive may carry: a unit under global/, repos/<scope>/ or observations/<scope>/.
UNIT_MEMBER = re.compile(r"(?:global|(?:repos|observations)/[A-Za-z0-9._-]+)/[A-Za-z0-9._-]+\.md")
MAX_MEMBER_BYTES = 256 * 1024
MAX_MEMBERS = 10_000
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def path_scope(name: str) -> str:
    """The scope a store path implies: `global`, or the directory under repos/ or observations/."""
    parts = name.split("/")
    return "global" if parts[0] == "global" else parts[1]


def unit_problem(scratch: Path, name: str, text: str) -> tuple[str | None, str | None]:
    """`(id, None)` for a unit import accepts at `name`, else `(None, why not)`."""
    if not UNIT_MEMBER.fullmatch(name) or any(part.startswith(".") for part in name.split("/")):
        return None, "not a unit path"
    if len(text.encode("utf-8")) > MAX_MEMBER_BYTES:
        return None, f"over {MAX_MEMBER_BYTES} bytes"
    path = scratch / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        unit = parse_unit(path, source_path=name, inferred_scope=path_scope(name))
    except ValueError as error:
        return None, str(error)
    if unit["scope"] != canonical_scope(path_scope(name)):
        return None, f"declares scope {unit['scope']!r} but sits under {path_scope(name)!r}"
    return unit["id"], None


def private_file(target: Path) -> BinaryIO:
    """A new file only this user can read, refused when the path exists or is a link (even a dangling one)."""
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    return os.fdopen(descriptor, "wb")


def anonymous(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def export_units(args: argparse.Namespace) -> int:
    """Write every unit import would accept to a new 0600 `.tar.gz`; skip anything else with a warning."""
    ensure_store()
    target, root = Path(args.file), memory_root()
    try:
        handle = private_file(target)
    except OSError as error:
        print(f"error: cannot create {target}: {error.strerror}; choose a new file", file=sys.stderr)
        return 2
    exported, folded = 0, set()
    with handle, tarfile.open(fileobj=handle, mode="w:gz") as bundle, tempfile.TemporaryDirectory() as scratch:
        for path in source_files():
            name = path.relative_to(root).as_posix()
            reason = "a link" if path.is_symlink() or not path.is_file() else None
            if reason is None and name.casefold() in folded:
                reason = "its name differs from another only by case"
            if reason is None:
                reason = unit_problem(Path(scratch), name, path.read_text(encoding="utf-8", errors="replace"))[1]
            if reason:
                print(f"skipped {name}: {reason}", file=sys.stderr)
                continue
            folded.add(name.casefold())
            bundle.add(path, arcname=name, recursive=False, filter=anonymous)
            exported += 1
    print(f"exported {exported} units to {target}")
    return 0


def read_member(bundle: tarfile.TarFile, member: tarfile.TarInfo) -> str:
    stream = bundle.extractfile(member)
    data = stream.read(MAX_MEMBER_BYTES + 1) if stream else b""
    if len(data) > MAX_MEMBER_BYTES:
        raise MemoryStoreError(f"{member.name!r} is over {MAX_MEMBER_BYTES} bytes")
    return data.decode("utf-8")


def archive_units(file: Path) -> dict[str, tuple[str, str]]:
    """`{store path: (text, id)}` for every member; raises MemoryStoreError, writing nothing, on any bad one."""
    units: dict[str, tuple[str, str]] = {}
    folded: dict[str, str] = {}
    ids: dict[str, str] = {}
    total = 0
    try:
        with tarfile.open(file, "r:gz") as bundle, tempfile.TemporaryDirectory() as scratch:
            for count, member in enumerate(bundle, 1):
                name = member.name
                if count > MAX_MEMBERS:
                    raise MemoryStoreError(f"more than {MAX_MEMBERS} members")
                if not member.isfile() or not UNIT_MEMBER.fullmatch(name):
                    raise MemoryStoreError(f"{name!r} is not a memory unit")
                if member.size > MAX_MEMBER_BYTES:
                    raise MemoryStoreError(f"{name!r} is over {MAX_MEMBER_BYTES} bytes")
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise MemoryStoreError(f"more than {MAX_TOTAL_BYTES} bytes in all")
                if name.casefold() in folded:
                    other = folded[name.casefold()]
                    raise MemoryStoreError(f"{name!r} and {other!r} are one file on a case-insensitive disk")
                folded[name.casefold()] = name
                text = read_member(bundle, member)
                ident, problem = unit_problem(Path(scratch), name, text)
                if problem:
                    raise MemoryStoreError(f"{name!r}: {problem}")
                if ident in ids:
                    raise MemoryStoreError(f"{name!r} and {ids[ident]!r} share the id {ident}")
                ids[ident] = name
                units[name] = (text, ident)
    except MemoryStoreError as error:
        raise MemoryStoreError(f"{file}: {error}; nothing imported") from error
    except (OSError, tarfile.TarError, UnicodeDecodeError) as error:
        raise MemoryStoreError(f"{file}: not a crew-mem.py export: {error}; nothing imported") from error
    return units


def plan_import(units: dict[str, tuple[str, str]]) -> tuple[list[tuple[Path, str]], list[str]]:
    """Under the store lock: the units to add and the stored ones that differ; raises on an id stored elsewhere."""
    root = memory_root()
    conn = refresh(write_indexes=False)
    try:
        stored = {row["id"]: row["source_path"] for row in conn.execute("SELECT id, source_path FROM units")}
    finally:
        conn.close()
    added, conflicts = [], []
    for name, (text, ident) in sorted(units.items()):
        target = root / name
        if target.exists():
            if target.read_text(encoding="utf-8", errors="replace") != text:
                conflicts.append(name)
        elif stored.get(ident, name) != name:
            raise MemoryStoreError(f"{name}: the id {ident} is already stored at {stored[ident]}; nothing imported")
        else:
            added.append((target, text))
    return added, conflicts


def import_units(args: argparse.Namespace) -> int:
    """Add an export's units to this store and index them; a unit already here with other text is kept.

    Exit 0 when every unit was added or already identical, 1 when at least one conflicted, 2 on a
    refused archive or a failed write (nothing is left behind).
    """
    ensure_store()
    units = archive_units(Path(args.file))
    plan: dict[str, list] = {"added": [], "conflicts": []}
    written: list[tuple[Path, str | None]] = []

    def write() -> list[tuple[Path, str | None]]:
        plan["added"], plan["conflicts"] = plan_import(units)
        for target, text in plan["added"]:
            if target.exists():
                raise MemoryStoreError(f"{target} appeared during the import; nothing imported")
            target.parent.mkdir(parents=True, exist_ok=True)
            written.append((target, None))
            atomic_write(target, text)
        return written

    if args.dry_run:
        with store_lock():
            plan["added"], plan["conflicts"] = plan_import(units)
    else:
        code = mutate(f"mem: import {len(units)} units", write, written)
        if code:
            return code
    added, conflicts = plan["added"], plan["conflicts"]
    verb = "would add" if args.dry_run else "added"
    unchanged = len(units) - len(added) - len(conflicts)
    print(f"{verb} {len(added)}, unchanged {unchanged}, kept {len(conflicts)} that differ")
    for name in conflicts:
        print(f"conflict: {name} differs from the stored unit; kept the stored one", file=sys.stderr)
    return 1 if conflicts else 0
