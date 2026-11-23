"""Filesystem helpers shared by every tool: one durable write, one JSON read."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write(path: Path, content: str) -> None:
    """Write a file via a sibling temp file, flushed and fsynced before the rename.

    The fsync is the point: a memory unit, an index, and a review report are written once and
    read by a later step, so a crash between write and rename must not leave the short file.
    The previous revision of the review report skipped the fsync, which is why there is one
    implementation here rather than one per package.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> Any:
    """Parse a JSON file, leaving OSError and JSONDecodeError to the caller's own message."""
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_object(path: Path, key: str) -> dict:
    """A JSON object that must carry a `key` list, or ValueError naming the file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path} has no {key!r} list")
    return payload
