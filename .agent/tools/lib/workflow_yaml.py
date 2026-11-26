"""A CI workflow as nested dicts, lists and strings: `load` returns it with the parser that read it.

`load` uses mikefarah `yq -o=json` when installed and this module's stdlib reader as the last
fallback (maps, lists, quoted and plain scalars, `|` / `>` blocks, comments; no anchors, tags or flow
maps: a flow list comes back as its raw text). Every scalar is a string, whichever parser read it: a
number keeps the spelling the workflow wrote (`3.10` stays `3.10`), a boolean is `true` or `false`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

KEY = re.compile(r"""^("[^"]*"|'[^']*'|[^\s'"#\-\[{][^:]*|-[^\s:][^:]*):(?:\s+(.*))?$""")
BLOCK_MARKS = ("|", "|-", "|+", ">", ">-", ">+")


def strip_comment(text: str) -> str:
    """The text without a trailing ` # comment`; a `#` inside quotes stays."""
    quote = ""
    for index, char in enumerate(text):
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or text[index - 1] in " \t"):
            return text[:index].rstrip()
    return text


def scalar(text: str) -> str:
    """One plain or quoted scalar as a string."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


class Lines:
    """The file as a cursor: `peek` is the next content line, `advance` consumes it."""

    def __init__(self, text: str) -> None:
        self.raw = text.splitlines()
        self.pos = 0
        self.cur: tuple[int, str] | None = None

    def peek(self) -> tuple[int, str] | None:
        if self.cur is None:
            while self.pos < len(self.raw) and (not self.raw[self.pos].strip()
                                                or self.raw[self.pos].lstrip().startswith("#")):
                self.pos += 1
            if self.pos >= len(self.raw):
                return None
            line = self.raw[self.pos]
            self.cur = (len(line) - len(line.lstrip(" ")), strip_comment(line.strip()))
        return self.cur

    def advance(self) -> None:
        self.peek()
        self.cur = None
        self.pos += 1

    def block(self, indent: int, folded: bool) -> str:
        """The block scalar that follows a `key: |` line, indented deeper than the key."""
        taken: list[str] = []
        while self.pos < len(self.raw):
            line = self.raw[self.pos]
            if line.strip() and len(line) - len(line.lstrip(" ")) <= indent:
                break
            taken.append(line)
            self.pos += 1
        margin = min((len(x) - len(x.lstrip(" ")) for x in taken if x.strip()), default=0)
        body = [x[margin:] if x.strip() else "" for x in taken]
        return (" ".join(x for x in body if x) if folded else "\n".join(body)).strip("\n")


def is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def parse_node(lines: Lines, indent: int) -> object:
    found = lines.peek()
    if found is None:
        return ""
    return parse_list(lines, found[0]) if is_item(found[1]) else parse_map(lines, indent)


def parse_list(lines: Lines, indent: int) -> list:
    items: list = []
    while True:
        found = lines.peek()
        if found is None or found[0] != indent or not is_item(found[1]):
            return items
        rest = found[1][1:].lstrip()
        offset = len(found[1]) - len(rest)
        if not rest:
            lines.advance()
            nested = lines.peek()
            items.append(parse_node(lines, nested[0]) if nested and nested[0] > indent else "")
        elif KEY.match(rest):
            lines.cur = (indent + offset, rest)
            items.append(parse_map(lines, indent + offset))
        else:
            lines.advance()
            items.append(scalar(rest))


def parse_map(lines: Lines, indent: int) -> dict:
    result: dict = {}
    while True:
        found = lines.peek()
        if found is None or found[0] != indent or is_item(found[1]):
            return result
        match = KEY.match(found[1])
        if not match:
            lines.advance()
            continue
        key, rest = scalar(match.group(1)), (match.group(2) or "").strip()
        lines.advance()
        if rest in BLOCK_MARKS:
            result[key] = lines.block(indent, rest.startswith(">"))
        elif not rest:
            nested = lines.peek()
            deeper = nested and (nested[0] > indent or (nested[0] == indent and is_item(nested[1])))
            result[key] = parse_node(lines, nested[0]) if deeper else ""
        else:
            result[key] = scalar(rest)


def parse(text: str) -> dict:
    """The document as nested dicts, lists and strings; an empty or non-map file is `{}`."""
    lines = Lines(text)
    found = lines.peek()
    if found is None or is_item(found[1]):
        return {}
    return parse_map(lines, found[0])


def as_strings(value: object) -> object:
    """A parsed document with every scalar spelled as a string (`true`, `22`; null is `''`)."""
    if isinstance(value, dict):
        return {str(key): as_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_strings(item) for item in value]
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def yq_parse(text: str) -> dict | None:
    """The document through mikefarah `yq -o=json`, or None when that yq is absent or refuses it."""
    if not shutil.which("yq"):
        return None
    try:
        version = subprocess.run(["yq", "--version"], capture_output=True, text=True, timeout=10).stdout
        if "mikefarah" not in version:
            return None
        done = subprocess.run(["yq", "-o=json", "."], input=text, capture_output=True, text=True, timeout=30)
        doc = json.loads(done.stdout, parse_float=str, parse_int=str) if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return as_strings(doc) if isinstance(doc, dict) else None


def load(text: str) -> tuple[dict, str]:
    """`(document, parser)`: `yq` when it read the file, else `stdlib` (this module's reader)."""
    doc = yq_parse(text)
    return (doc, "yq") if doc is not None else (parse(text), "stdlib")
