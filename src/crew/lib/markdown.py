"""Markdown structure, read in one place: fenced code blocks and frontmatter.

`frontmatter` parses the block with PyYAML (agents and skills are YAML); a Cursor rule's frontmatter is
not YAML (`globs: **/*.ts`), so a rule reads `frontmatter_text`. PyYAML loads only when asked.
"""

from __future__ import annotations

import re

FENCED = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.M | re.S)  # group 1: the info string; 2: the body
FRONTMATTER = re.compile(r"\A---\n(.*?\n)?---(?:\n|\Z)", re.S)


def fenced_blocks(text: str, info: str | None = None) -> list[str]:
    """The bodies of the fenced code blocks, in order; with `info`, only the blocks whose info string it is."""
    return [body for tag, body in FENCED.findall(text) if info is None or tag.strip() == info]


def frontmatter_text(text: str) -> tuple[str | None, str]:
    """`(block, "")`, the text between the opening and closing `---`, or `(None, why)` when missing or unclosed."""
    if not text.startswith("---\n"):
        return None, "add YAML frontmatter at the start of the file"
    found = FRONTMATTER.match(text)
    return (found.group(1) or "", "") if found else (None, "close YAML frontmatter")


def frontmatter(text: str) -> tuple[dict | None, str]:
    """`(fields, "")`, the YAML frontmatter as a map, or `(None, why)`."""
    block, error = frontmatter_text(text)
    if block is None:
        return None, error
    import yaml

    try:
        fields = yaml.safe_load(block)
    except yaml.YAMLError as problem:
        return None, f"frontmatter is not YAML: {str(problem).splitlines()[0]}"
    return (fields, "") if isinstance(fields, dict) else (None, "frontmatter is not a YAML map")
