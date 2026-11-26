"""The unit format: vocabulary, frontmatter scalars and lists, parsing, and rendering back to Markdown.

One unit is one Markdown file. Parsing and rendering are exact inverses (`json.dumps` scalars decoded
by `parse_scalar`, which also accepts the YAML spellings hand-authored units contain), and keys the
model does not own keep their text and order, so a hand-authored unit round-trips intact.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from memory_paths import canonical_scope, memory_root, scope_from_path, today

from lib.files import atomic_write


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


TYPES = {
    "user", "feedback", "project", "reference", "failure-shield", "procedure",
    "observation",
}
STATUSES = {"active", "superseded", "archived"}

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


def frontmatter_fields(lines: list[str]) -> tuple[dict, dict]:
    """The top-level frontmatter keys and the ones nested under `metadata:`.

    A key with no indent is top-level; an indented key after `metadata:` belongs to that block
    until the next top-level key, so an unknown nested key stays where the author wrote it.
    """
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
    return data, metadata


def parse_unit(
    path: Path, source_path: str | None = None, inferred_scope: str | None = None
) -> dict:
    """The unit a stored file holds, with its fingerprint fields and any unmodeled keys."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    lines, extras, body = split_frontmatter(text, path)
    data, metadata = frontmatter_fields(lines)
    unit_type = data.get("type") or metadata.get("type")
    ident = data.get("id") or data.get("name")
    if not unit_type or not ident:
        raise ValueError("frontmatter requires id/name and type/metadata.type")
    if unit_type not in TYPES:
        raise ValueError(f"unknown memory type: {unit_type}")
    scope = canonical_scope(data.get("scope") or inferred_scope or scope_from_path(path))
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


def render_unit(unit: dict) -> str:
    """The Markdown a unit is stored as; `parse_unit` reads it back to the same record."""
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


def update_frontmatter(path: Path, changes: dict) -> tuple[Path, str]:
    """Apply `changes` to a stored unit and return its path with the content it replaced."""
    unit = parse_unit(path)
    unit.update(changes)
    unit["modified"] = today()
    previous = path.read_text(encoding="utf-8")
    atomic_write(path, render_unit(unit))
    return path, previous
