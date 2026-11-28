"""Bounded output for model-facing commands: a size ceiling, a row limit, and an honest marker.

A model that receives a silently cut list assumes the list was complete, so every truncation prints
one marker naming what was dropped and how to get the rest. The edge rule is the one
`task-context` already uses: append-only logs and reports whose identity fields come last keep
their tail, everything else keeps its head.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

# A default high enough to leave ordinary output untouched, low enough to stop a runaway table or a
# whole spec from spending the caller's context on one call.
DEFAULT_MAX_CHARS = 20_000


def hint(flag: str = "--max-chars") -> str:
    """The one place the "how to get the rest" wording lives."""
    if flag == "--limit":
        return "raise --limit to see the rest"
    return f"raise {flag} to see the rest"


def truncate(text: str, max_chars: int, *, what: str = "output", tail: bool = False, flag: str = "--max-chars") -> str:
    """`text` clipped to `max_chars` on a line boundary, with a marker naming what was dropped."""
    if max_chars < 1:
        raise ValueError(f"{flag} must be at least 1")
    if len(text) <= max_chars:
        return text
    if tail:
        kept = text[-max_chars:]
        newline = kept.find("\n")
        kept = kept[newline + 1 :] if newline >= 0 else kept
    else:
        kept = text[:max_chars]
        newline = kept.rfind("\n")
        kept = kept[:newline] if newline > 0 else kept
    dropped = len(text) - len(kept)
    marker = f"[truncated: {what} kept {'last' if tail else 'first'} {len(kept)} of {len(text)} chars, {dropped} dropped; {hint(flag)}]"
    return f"{marker}\n{kept}" if tail else f"{kept}\n{marker}"


def rows_limit(rows: Sequence[Any], limit: int | None) -> tuple[list[Any], str]:
    """At most `limit` rows, plus a marker naming how many were dropped."""
    if limit is None or limit >= len(rows):
        return list(rows), ""
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    dropped = len(rows) - limit
    return list(rows[:limit]), (f"[truncated: showed {limit} of {len(rows)} rows, {dropped} dropped; {hint('--limit')}]")


def print_lines(lines: Iterable[str], max_chars: int, *, what: str = "output", tail: bool = False, flag: str = "--max-chars") -> None:
    """Print `lines` joined by newlines, clipped with the marker when over `max_chars`."""
    print(truncate("\n".join(lines), max_chars, what=what, tail=tail, flag=flag))


def json_envelope(items: list[Any], limit: int | None, max_chars: int, *, what: str = "items") -> dict[str, Any]:
    """A collection as one object, clipped or not: `{"items": [...], "returned": n, "total": N,
    "truncated": bool, "what": ...}`, plus a `hint` naming `--limit` (a row limit cut the list) or
    `--max-chars` (the size ceiling did) when `truncated`. A reader parses one shape every time."""
    total = len(items)
    kept, _ = rows_limit(items, limit)
    while kept and len(json.dumps(kept, indent=2)) > max_chars:
        kept = kept[:-1]
    envelope: dict[str, Any] = {"items": kept, "returned": len(kept), "total": total, "truncated": len(kept) < total, "what": what}
    if envelope["truncated"]:
        envelope["hint"] = hint("--limit" if limit is not None and limit < total else "--max-chars")
    return envelope


def json_payload(items: list[Any], limit: int | None, max_chars: int, *, what: str = "items") -> str:
    """JSON for a collection: a plain array when complete, the `json_envelope` object when clipped.

    An array cannot carry a "there is more" flag, so a clipped result is the envelope — still valid
    JSON with no prose on stdout, and impossible to mistake for a complete list.
    """
    envelope = json_envelope(items, limit, max_chars, what=what)
    return json.dumps(envelope if envelope["truncated"] else envelope["items"], indent=2)


def bounded_json(payload: Any, max_chars: int, *, what: str = "result") -> str:
    """Any JSON payload within `max_chars`, staying valid JSON and naming what was cut.

    A list value is trimmed from its last element and gains `truncated`/`total`; a payload that is
    still too large becomes `{"truncated": true, "what": ..., "chars": N, "preview": "..."}`, so the
    caller always parses and always learns that the value is partial.
    """
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if len(encoded) <= max_chars:
        return encoded
    if isinstance(payload, dict):
        trimmed = dict(payload)
        for key in sorted(trimmed, key=lambda name: -len(json.dumps(trimmed[name], default=str))):
            value = trimmed[key]
            if not isinstance(value, list):
                continue
            total = len(value)
            kept = list(value)
            while kept and len(json.dumps({**trimmed, key: kept}, indent=2, sort_keys=True, default=str)) > max_chars:
                kept = kept[:-1]
            if len(kept) < total:
                trimmed[key] = kept
                trimmed["truncated"] = True
                trimmed[f"{key}_total"] = total
                trimmed["hint"] = hint("--max-chars")
            if len(json.dumps(trimmed, indent=2, sort_keys=True, default=str)) <= max_chars:
                return json.dumps(trimmed, indent=2, sort_keys=True)
    envelope = {"truncated": True, "what": what, "chars": len(encoded), "preview": encoded[: max(0, max_chars - 120)], "hint": hint("--max-chars")}
    return json.dumps(envelope, indent=2)
