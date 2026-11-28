"""The Cursor CLI ("unverified live"): it loads the cursor adapter's local plugin and sends the same payloads, so it
reuses that adapter's normalize and encode. Its own file is the deny tokens added to ~/.cursor/cli-config.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from crew.harness import adapters, cursor

ID = "cursor-cli"


def normalize(native: str, payload: dict, harness: str = ID) -> dict | None:
    return cursor.normalize(native, payload, harness)


def encode(native: str, result: dict) -> tuple[str, str, int]:
    return cursor.encode(native, result)


def render(checkout: Path, home: Path) -> dict[str, tuple[str, str]]:
    """`deny`: tokens added to the CLI's config when it has one; the rest is the cursor adapter's plugin."""
    return {".cursor/cli-config.json": ("deny", json.dumps(adapters.manifest(ID)["deny_tokens"]))}
