"""Unified-diff parsing and the size policy over it: path quoting, file and hunk records.

One parser for the hunk splitter and the finding model, so a cited id and an accepted id agree. A
generated file (lockfile, snapshot, bundle) or a hunk over `SUPPRESS_LINES`/`SUPPRESS_CHARS` loses
its text but keeps its hunk ids; only `byName` lets a package collapse a body.
"""

from __future__ import annotations

import re

GENERATED = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.sum|Cargo\.lock|poetry\.lock|uv\.lock"
    r"|Gemfile\.lock|composer\.lock)$|__snapshots__/|\.snap$|(^|/)dist/|\.min\.(js|css)$|\.map$"
    r"|\.gen\.|_generated|\.generated\.|(^|/)generated/|(^|/)__generated__/|\.pb\.go$"
    r"|_pb2(_grpc)?\.py$|(^|/)vendor/|\.bundled\.(json|ya?ml)$"
)
SUPPRESS_LINES = 5000
SUPPRESS_CHARS = 500_000
LARGE_LINES = 400
MAX_LINE_CHARS = 5000


def new_file(path: str, old_path: str) -> dict:
    """A file record before its hunks are seen; `byName` is what a package may collapse."""
    return {
        "path": path,
        "oldPath": old_path,
        "status": "modified",
        "generated": bool(GENERATED.search(path)),
        "byName": bool(GENERATED.search(path)),
        "hunkIds": [],
    }


def apply_limits(files: list[dict], hunks: list[dict]) -> None:
    """Flag oversized and generated-by-content files, and cut a line that would dwarf the package."""
    by_file: dict[str, list[dict]] = {}
    for hunk in hunks:
        by_file.setdefault(hunk["file"], []).append(hunk)
    for entry in files:
        owned = by_file.get(entry["path"], [])
        total = sum(h["additions"] + h["deletions"] for h in owned)
        chars = sum(len(line["s"]) for h in owned for line in h["lines"])
        longest = max((len(line["s"]) for h in owned for line in h["lines"]), default=0)
        # Minified or machine-written content counts as generated even with a plain name.
        if longest > 2000 or (chars and chars / max(total, 1) > 400):
            entry["generated"] = True
        if total > SUPPRESS_LINES or chars > SUPPRESS_CHARS:
            entry["suppressed"] = True
            entry["size"] = chars
            for h in owned:
                h["suppressed"] = True
                h["lines"] = []
            continue
        if total > LARGE_LINES:
            entry["large"] = True
        for h in owned:
            for line in h["lines"]:
                if len(line["s"]) > MAX_LINE_CHARS:
                    line["cut"] = len(line["s"])
                    line["s"] = line["s"][:MAX_LINE_CHARS]


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
QUOTED = r'"((?:[^"\\]|\\.)*)"'
QUOTED_HEADER = re.compile(rf"^diff --git (?:{QUOTED}|(\S+)) (?:{QUOTED}|(\S+))$")
PLAIN_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$")
C_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, '"': 34, "\\": 92}


def unquote(token: str) -> str:
    """Decode git's C-style path quoting (`"caf\\303\\251.md"`), used for non-ASCII and control characters."""
    if len(token) < 2 or not (token.startswith('"') and token.endswith('"')):
        return token
    body, out, index = token[1:-1], bytearray(), 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out += char.encode("utf-8")
            index += 1
            continue
        octal = re.match(r"[0-7]{1,3}", body[index + 1 :])
        if octal:
            out.append(int(octal.group(0), 8) & 0xFF)
            index += 1 + len(octal.group(0))
            continue
        out.append(C_ESCAPES.get(body[index + 1 : index + 2], ord(body[index + 1 : index + 2] or "\\")))
        index += 2
    return out.decode("utf-8", errors="replace")


def header_paths(line: str) -> tuple[str, str]:
    """Old and new path from a `diff --git` line, quoted or not; empty strings when unparseable."""
    quoted = QUOTED_HEADER.match(line) if '"' in line else None
    if quoted:
        old = unquote(f'"{quoted.group(1)}"') if quoted.group(1) is not None else quoted.group(2)
        new = unquote(f'"{quoted.group(3)}"') if quoted.group(3) is not None else quoted.group(4)
        return old.removeprefix("a/"), new.removeprefix("b/")
    plain = PLAIN_HEADER.match(line)
    return (plain.group(1), plain.group(2)) if plain else ("", "")


def new_file_status(entry: dict, line: str) -> None:
    """Record a file-level header line (`new file mode`, `rename from`, `Binary files`, …)."""
    if line.startswith("new file mode"):
        entry["status"] = "added"
    elif line.startswith("deleted file mode"):
        entry["status"] = "deleted"
    elif line.startswith("rename from "):
        entry["status"] = "renamed"
        entry["oldPath"] = unquote(line[len("rename from ") :])
    elif line.startswith("rename to "):
        entry["path"] = unquote(line[len("rename to ") :])
    elif line.startswith("Binary files "):
        entry["status"] = "binary"


def open_hunk(line: str, header: re.Match, current: dict, hunks: list[dict]) -> dict:
    """The hunk a `@@ … @@` line starts, numbered in diff order."""
    old_no, new_no = int(header.group(1)), int(header.group(3))
    hunk = {
        "id": f"h{len(hunks) + 1}",
        "file": current["path"],
        "oldFile": current["oldPath"],
        "header": line[: line.index("@@", 2) + 2],
        "context": header.group(5) or "",
        "oldStart": old_no,
        "newStart": new_no,
        "additions": 0,
        "deletions": 0,
        "lines": [],
    }
    hunks.append(hunk)
    current["hunkIds"].append(hunk["id"])
    return hunk


def hunk_line(hunk: dict, line: str, numbers: dict[str, int]) -> None:
    """Append one body line to `hunk`, advancing the old and new line counters in `numbers`."""
    kind = line[:1]
    if kind == "+":
        hunk["lines"].append({"t": "+", "s": line[1:], "n": numbers["new"]})
        numbers["new"] += 1
        hunk["additions"] += 1
    elif kind == "-":
        hunk["lines"].append({"t": "-", "s": line[1:], "o": numbers["old"]})
        numbers["old"] += 1
        hunk["deletions"] += 1
    elif kind == " ":
        hunk["lines"].append({"t": " ", "s": line[1:], "o": numbers["old"], "n": numbers["new"]})
        numbers["old"] += 1
        numbers["new"] += 1
    elif kind == "\\":
        hunk["lines"].append({"t": "\\", "s": line[1:]})
    elif line == "":
        # Some tools strip the leading space of an empty context line.
        hunk["lines"].append({"t": " ", "s": "", "o": numbers["old"], "n": numbers["new"]})
        numbers["old"] += 1
        numbers["new"] += 1


def synthetic_hunks(files: list[dict], hunks: list[dict]) -> None:
    """Give every file with no textual hunk one id, so it can still be placed in a layer."""
    for entry in files:
        if entry["hunkIds"]:
            continue
        header = {"binary": "(binary file)", "renamed": "(renamed, no content change)"}.get(entry["status"], "(no textual changes)")
        hunk = {
            "id": f"h{len(hunks) + 1}",
            "file": entry["path"],
            "oldFile": entry["oldPath"],
            "header": header,
            "context": "",
            "oldStart": 0,
            "newStart": 0,
            "additions": 0,
            "deletions": 0,
            "lines": [],
        }
        hunks.append(hunk)
        entry["hunkIds"].append(hunk["id"])


def parse(diff: str) -> dict:
    """The files and numbered hunks a unified diff holds."""
    files: list[dict] = []
    hunks: list[dict] = []
    current: dict | None = None
    hunk: dict | None = None
    numbers = {"old": 0, "new": 0}

    lines = diff.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("diff --git "):
            old_path, path = header_paths(line)
            current = new_file(path, old_path or path)
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue

        if hunk is None or line[:1] not in " +-\\":
            new_file_status(current, line)

        header = HUNK_HEADER.match(line)
        if header:
            hunk = open_hunk(line, header, current, hunks)
            numbers = {"old": hunk["oldStart"], "new": hunk["newStart"]}
            continue

        if hunk is None:
            continue
        if line == "" and index >= len(lines) - 1:
            continue
        hunk_line(hunk, line, numbers)

    synthetic_hunks(files, hunks)
    apply_limits(files, hunks)
    return {"files": files, "hunks": hunks}
