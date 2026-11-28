"""Filesystem helpers shared by every tool: one durable write, one JSON read, one AGENTS.md setting read."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from crew.lib.markdown import FENCED


def agents_setting(root: Path, name: str) -> str:
    """The value of the first `<name>: <value>` line outside a fenced code block in the `AGENTS.md` at
    `root`, or '' when absent.

    The reader of the plain-line settings a repository declares (`src/crew/AGENTS.md`).
    """
    try:
        text = (root / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    found = re.search(rf"^{re.escape(name)}:[ \t]*(\S.*?)[ \t]*$", FENCED.sub("", text), re.M | re.I)
    return found.group(1) if found else ""


def atomic_write(path: Path, content: str) -> None:
    """Write a file via a sibling temp file, flushed and fsynced before the rename.

    The fsync is the point: a memory unit, an index, and a review report are written once and
    read by a later step, so a crash between write and rename must not leave the short file.
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


def checkout() -> Path:
    """The el-capitan checkout: the tree this package runs from (`uv run`), else the one ~/.agent/venv was built from."""
    here = Path(__file__).resolve().parents[3]
    if (here / "install.sh").is_file():
        return here
    try:
        recorded = read_json_object(Path.home() / ".agent" / "install-manifest.json").get("venv") or {}
    except ValueError:
        recorded = {}
    return Path(recorded.get("checkout") or here)


def read_json_object(path: Path, key: str | None = None) -> dict:
    """A JSON object (carrying a `key` list when one is named), or ValueError naming the file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    if key is not None and not isinstance(payload.get(key), list):
        raise ValueError(f"{path} has no {key!r} list")
    return payload
