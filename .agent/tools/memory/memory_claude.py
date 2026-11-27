"""Claude Code auto-memory into crew memory: `import-claude` drafts, `--check` counts, `--archive` moves.

Each `<config dir>/projects/<folder>/memory/*.md` is untrusted: only its body and Claude `type` are read.
An entry is imported when a stored unit holds its `source_identity` and `source_sha256`; a symlink, a
nested file, a `MEMORY.md` with text besides links, an edited import, or a folder that does not resolve
to exactly one directory (or text naming another repo) is listed for review, never drafted.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from memory_frontmatter import frontmatter_fields, parse_unit, render_unit, split_frontmatter
from memory_paths import memory_root, repo_key, slug, source_files, today
from memory_store import ensure_store

from lib.files import atomic_write

CLAUDE_TYPES = ("user", "feedback", "project", "reference")
SOURCE = "claude-memory:"
HASH_KEY = "source_sha256"
# A repository key shorter than this ("ui", "db") is too often an ordinary word in a note to mean the note
# is about that repository.
MIN_REPO_KEY = 3
LINK_LINE = re.compile(r"^\s*[-*]\s+\[[^\]]*\]\([^)\s]+\.md\)")
REVIEW_HINT = "decide, then delete or move the file"


@dataclass
class Entry:
    """One auto-memory file and its verdict: imported, stored, drafted, draft or review."""
    path: Path
    verdict: str
    detail: str = ""
    text: str = ""


def default_config_dirs() -> list[Path]:
    """~/.claude and `$CLAUDE_CONFIG_DIR`, each existing one once."""
    named = [Path.home() / ".claude"]
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        named.append(Path(os.environ["CLAUDE_CONFIG_DIR"]))
    found: dict[str, Path] = {}
    for directory in named:
        if directory.is_dir():
            found.setdefault(os.path.realpath(directory), Path(os.path.abspath(directory)))
    return list(found.values())


def identity(path: Path) -> str:
    return SOURCE + os.path.abspath(path)


def short_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()[:8]


def index_text(path: Path) -> list[str]:
    """The lines of a `MEMORY.md` that are not `- [..](x.md)` links (a link line may carry a description)."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [line for line in lines if line.strip() and not LINK_LINE.match(line)]


def memory_files(config_dirs: list[Path]) -> tuple[list[Path], list[Entry]]:
    """The flat entry files, and a review entry for each symlink, nested file or `MEMORY.md` with text."""
    files: list[Path] = []
    flagged: list[Entry] = []
    for directory in config_dirs:
        for memory in sorted(directory.glob("projects/*/memory")):
            if memory.is_symlink() or not memory.is_dir():
                continue
            for top, dirs, names in os.walk(memory):
                for name in sorted(dirs + names):
                    path = Path(top) / name
                    if not name.endswith(".md") and not path.is_symlink():
                        continue
                    if path.is_symlink():
                        flagged.append(Entry(path, "review", "symlink"))
                    elif path.parent != memory:
                        flagged.append(Entry(path, "review", "nested"))
                    elif name != "MEMORY.md":
                        files.append(path)
                    elif index_text(path):
                        flagged.append(Entry(path, "review", "MEMORY.md holds text besides its links"))
    return files, flagged


def stored() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """By source identity, the stored unit's (source hash, id); by stripped body, a stored unit's id."""
    sources: dict[str, tuple[str, str]] = {}
    bodies: dict[str, str] = {}
    for path in source_files():
        try:
            unit = parse_unit(path)
        except (OSError, ValueError):
            continue
        bodies.setdefault(unit["body"].strip(), unit["id"])
        value = unit.get("source_identity")
        if isinstance(value, str) and value.startswith(SOURCE):
            sha = next((line.split(":", 1)[1].strip() for line in unit["extra_frontmatter"]
                        if line.startswith(f"{HASH_KEY}:")), "")
            sources[value] = (sha, unit["id"])
    return sources, bodies


def drafted_identities() -> set[str]:
    found = set()
    for path in (memory_root() / ".inbox").glob("*.md"):
        try:
            found.add(parse_unit(path, inferred_scope="global").get("source_identity") or "")
        except (OSError, ValueError):
            continue
    return found


def encoded(path: str) -> str:
    """A path as Claude Code names its project folder: every character but a letter or digit is `-`."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def folder_matches(folder: str) -> list[Path]:
    """Every existing directory whose encoded path is `folder`, found by walking from `/`."""
    def walk(directory: Path) -> list[Path]:
        try:
            children = sorted(directory.iterdir())
        except OSError:
            return []
        found: list[Path] = []
        for child in children:
            name = encoded(str(child))
            if folder != name and not folder.startswith(name + "-"):
                continue
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            found += [child] if folder == name else walk(child)
        return found
    return walk(Path("/")) if folder.startswith("-") else []


def resolve(folder: str) -> tuple[str | None, str]:
    """The scope of a project folder, or None with the reason it is left for review."""
    found = folder_matches(folder)
    if not found:
        return None, "the project folder does not resolve to a directory on disk"
    if len(found) > 1:
        return None, f"the project folder matches {len(found)} directories"
    return repo_key(found[0]), ""


def read_entry(path: Path) -> tuple[str, str]:
    """The Claude type and the body of an entry; every other frontmatter key is ignored. ValueError names a defect."""
    text = path.read_text(encoding="utf-8", errors="replace")
    data: dict = {}
    metadata: dict = {}
    body = text
    if text.startswith("---\n"):
        lines, _, body = split_frontmatter(text, path)
        data, metadata = frontmatter_fields(lines)
    kind = data.get("type") or metadata.get("type")
    if kind not in CLAUDE_TYPES:
        raise ValueError(f"no Claude type ({', '.join(CLAUDE_TYPES)}): {kind!r}")
    if not body.strip():
        raise ValueError("empty body")
    return str(kind), body.strip("\n") + "\n"


def title_of(path: Path, kind: str) -> str:
    stem = path.stem[len(kind) + 1:] if path.stem.startswith(f"{kind}_") else path.stem
    words = re.sub(r"[-_\s]+", " ", stem).strip() or "memory"
    return words[0].upper() + words[1:]


def other_repo(text: str, own: str, known: set[str]) -> str | None:
    """A known repository key other than `own` that the text names as a word, or None."""
    for key in sorted(known - {own}):
        if len(key) >= MIN_REPO_KEY and re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", text, re.I):
            return key
    return None


def draft_text(kind: str, scope: str, path: Path, body: str) -> str:
    source = identity(path)
    title = title_of(path, kind)
    return render_unit({
        "id": f"{kind}-{slug(title)}-{short_hash(source)}", "type": kind, "scope": scope, "title": title,
        "paths": [], "keywords": [], "status": "active", "superseded_by": None, "created": today(),
        "modified": today(), "review_by": None, "evidence": [source], "source_identity": source, "uses": 0,
        "last_used": None, "helped": 0, "misled": 0, "body": body,
        "extra_frontmatter": [f"{HASH_KEY}: {hashlib.sha256(path.read_bytes()).hexdigest()}"]})


def judge(path: Path, context: dict) -> Entry:
    """The verdict on one flat entry file, given the store, the inbox and the resolved folders."""
    source = identity(path)
    if source in context["sources"]:
        sha, ident = context["sources"][source]
        if sha == hashlib.sha256(path.read_bytes()).hexdigest():
            return Entry(path, "imported", ident)
        return Entry(path, "review", f"edited since its import as {ident}; supersede that unit")
    try:
        if re.search(r"[\x00-\x1f]", source):
            raise ValueError("the path holds a control character")
        kind, body = read_entry(path)
    except (OSError, ValueError) as error:
        return Entry(path, "review", str(error))
    if body.strip() in context["bodies"]:
        return Entry(path, "stored", context["bodies"][body.strip()])
    if source in context["drafted"]:
        return Entry(path, "drafted")
    scope, reason = context["folders"][path.parent.parent.name]
    named = other_repo(body, scope, context["known"]) if scope else None
    if not scope:
        return Entry(path, "review", reason)
    if named:
        return Entry(path, "review", f"names the repo {named}, not its folder's ({scope})")
    return Entry(path, "draft", scope, draft_text(kind, scope, path, body))


def classify(config_dirs: list[Path]) -> list[Entry]:
    """Every auto-memory file under the config dirs with its verdict."""
    files, entries = memory_files(config_dirs)
    sources, bodies = stored()
    folders = {folder: resolve(folder) for folder in {path.parent.parent.name for path in files}}
    known = {scope for scope, _ in folders.values() if scope} | {d.name for d in (memory_root() / "repos").glob("*")}
    context = {"sources": sources, "bodies": bodies, "drafted": drafted_identities(), "folders": folders,
               "known": known}
    return entries + [judge(path, context) for path in files]


def remaining(config_dirs: list[Path]) -> tuple[list[Entry], list[Entry]]:
    """The entries still to import (draft or drafted) and those left for the owner's review."""
    entries = classify(config_dirs)
    return ([e for e in entries if e.verdict in ("draft", "drafted")], [e for e in entries if e.verdict == "review"])


def review_line(entry: Entry) -> str:
    return f"review {entry.path}: {entry.detail}; {REVIEW_HINT}"


def check(config_dirs: list[Path]) -> int:
    """List what keeps auto-memory on: entries to import and entries for review; exit 1 when any remain."""
    entries = classify(config_dirs)
    for entry in entries:
        if entry.verdict in ("draft", "drafted"):
            print(f"not imported: {entry.path}")
        elif entry.verdict == "review":
            print(review_line(entry))
        elif entry.verdict == "stored":
            print(f"already stored as {entry.detail}: {entry.path} (--archive moves it)")
    return 1 if any(entry.verdict in ("draft", "drafted", "review") for entry in entries) else 0


def archive(config_dirs: list[Path], dry_run: bool) -> int:
    """Move each imported or already-stored original, then each link-only `MEMORY.md` whose entries all went."""
    target = Path.home() / ".agent" / "archive" / f"claude-memory-{time.strftime('%Y%m%dT%H%M%S')}"
    verb = "would archive" if dry_run else "archived"
    moved: set[Path] = set()
    for entry in classify(config_dirs):
        if entry.verdict not in ("imported", "stored"):
            reason = entry.detail if entry.verdict == "review" else "not imported yet"
            print(f"kept {entry.path}: {reason}")
            continue
        moved.add(entry.path)
        move(entry.path, target, dry_run)
        print(f"{verb} {entry.path}")
    for directory in sorted({path.parent for path in moved}):
        index = directory / "MEMORY.md"
        if not index.is_file() or index.is_symlink() or index_text(index):
            continue
        listed = re.findall(r"\]\(([^)\s]+\.md)\)", index.read_text(encoding="utf-8", errors="replace"))
        left = [name for name in listed if (directory / name).exists() and directory / name not in moved]
        if left:
            print(f"kept {index}: it lists entries not archived ({', '.join(left)})")
            continue
        move(index, target, dry_run)
        print(f"{verb} {index}")
    return 0


def move(path: Path, target: Path, dry_run: bool) -> None:
    if dry_run:
        return
    destination = target / Path(os.path.abspath(path)).relative_to("/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(destination))


def import_claude(args: argparse.Namespace) -> int:
    """`import-claude`: draft the entries (`--dry-run` prints), `--check` lists what remains, `--archive` moves."""
    config_dirs = [Path(os.path.abspath(name)) for name in args.config_dir] or default_config_dirs()
    if args.check:
        return check(config_dirs)
    if args.archive:
        return archive(config_dirs, args.dry_run)
    ensure_store()
    drafted = 0
    for entry in classify(config_dirs):
        if entry.verdict == "draft":
            name = f"claude-{slug(entry.path.stem)}-{short_hash(identity(entry.path))}.md"
            if not args.dry_run:
                atomic_write(memory_root() / ".inbox" / name, entry.text)
            drafted += 1
            print(f"{'would draft' if args.dry_run else 'drafted'} {name}")
        elif entry.verdict == "review":
            print(review_line(entry))
        elif entry.verdict == "stored":
            print(f"skipped {entry.path}: its text is already stored as {entry.detail} (--archive moves it)")
        else:
            print(f"skipped {entry.path}: already {entry.verdict}")
    if drafted and not args.dry_run:
        print("next: review the drafts, then crew-mem.py import-inbox <the approved names>")
    return 0
