#!/usr/bin/env python3
"""One frontmatter value: decoding a scalar, an inline list, and the typed accessors over them.

Split from the unit format so that file describes the record and this one describes a single
field. `render_unit` writes scalars with `json.dumps`, so `parse_scalar` unescapes with the same
decoder; the YAML spellings it still accepts (bare nulls, doubled single quotes, comma lists) are
what hand-authored units contain, and dropping any of them would refuse a file the model wrote.
"""
from __future__ import annotations

import json


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
