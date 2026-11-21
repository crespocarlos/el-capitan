#!/usr/bin/env python3
"""Document discovery and the path helpers every lint family shares.

`files` is the whole in-scope document set — rules, agents, skills and their references, the tool
catalog page, the harness settings, and the hook scripts — so a family module never re-derives it.
The two helpers are here for the same reason: several families need them, and one definition keeps
a finding's file and line consistent across them.
"""
from __future__ import annotations

from pathlib import Path

PATTERNS = (
    "rules/*.mdc",
    ".cursor/rules/*.mdc",
    ".cursor/agents/**/*.md",
    ".cursor/skills/**/SKILL.md",
    ".cursor/skills/**/references/*.md",
    ".agent/tools/*.md",
    ".claude/CLAUDE.md",
    ".claude/settings.json",
    ".cursor/hooks.template.json",
    ".claude/hooks/*.sh",
    ".claude/hooks/guard/*.sh",
)


def files(root: Path) -> list[Path]:
    """Every in-scope document under `root`, deduplicated and sorted."""
    result: set[Path] = set()
    for pattern in PATTERNS:
        result.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(result)


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1
