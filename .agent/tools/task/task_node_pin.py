"""Which Node a repository asks for, if any.

el-capitan drives repos that are not Node projects, so the pin is found, never assumed. The first
file that names a Node wins: `.nvmrc`, `.node-version`, `.tool-versions` (its `nodejs` line, or
`node`), then `package.json` `engines.node`. With none, `("none", "")` comes back and the caller
leaves the PATH alone: a Python-only repo is never forced onto a Node it did not ask for.

An alias such as `lts/*` or `system` is returned as written; the caller finds no install for it and
keeps the PATH's own Node.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from task_verify_env import required_node

NONE = ("none", "")
VERSION = re.compile(r"\d+(?:\.\d+){0,2}")


def tool_versions_pin(text: str) -> str:
    """The version on the `nodejs` (or `node`) line of an asdf `.tool-versions`, or ''."""
    for line in text.splitlines():
        parts = line.split("#")[0].split()
        if len(parts) >= 2 and parts[0] in ("nodejs", "node"):
            return parts[1].removeprefix("v")
    return ""


def engines_pin(text: str) -> str:
    """The first version in `engines.node` (`>=22.18`, `^20.3.0 || ^22`), or ''."""
    try:
        spec = json.loads(text)["engines"]["node"]
    except (ValueError, KeyError, TypeError):
        return ""
    found = VERSION.search(spec) if isinstance(spec, str) else None
    return found.group(0) if found else ""


def node_pin(read: Callable[[str], "str | None"]) -> tuple[str, str]:
    """`(source, required)` for the first pin `read(path)` can show, else `("none", "")`."""
    for path, parse in ((".nvmrc", required_node), (".node-version", required_node),
                        (".tool-versions", tool_versions_pin), ("package.json", engines_pin)):
        required = parse(read(path) or "")
        if required:
            return ("package.json engines.node" if path == "package.json" else path), required
    return NONE
