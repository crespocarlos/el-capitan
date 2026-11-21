#!/usr/bin/env python3
"""Split a unified diff into numbered hunks for the reviewer layer map.

Writes `hunks.json`, `hunks.md`, `hunks.index.md`, and `package.diff` to `--out`. Every hunk gets a
stable id (`h1`, `h2`, …) in diff order, and a file with no textual hunk (binary, pure rename, mode
change) still gets one, so every changed file can be placed in a layer — the ids the persona Reading
map and the `coverage` gate share. `hunks.md` feeds the layer-mapping pass, `hunks.index.md` the
persona package that already holds the diff, and `package.diff` omits generated files' bodies.

Self-contained on purpose: parsing is project-agnostic, because a review that silently loses its
layer map to a missing external tool is worse than one that never had a map. A file over
`SUPPRESS_LINES`/`SUPPRESS_CHARS` keeps its hunk ids and drops its lines, so hunks stay addressable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.output import DEFAULT_MAX_CHARS, bounded_json  # noqa: E402

GENERATED = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.sum|Cargo\.lock|poetry\.lock|uv\.lock"
    r"|Gemfile\.lock|composer\.lock)$|__snapshots__/|\.snap$|(^|/)dist/|\.min\.(js|css)$|\.map$"
    r"|\.gen\.|_generated|\.generated\.|(^|/)generated/|(^|/)__generated__/|\.pb\.go$"
    r"|_pb2(_grpc)?\.py$|(^|/)vendor/|\.bundled\.(json|ya?ml)$"
)
SUPPRESS_LINES = 5000
SUPPRESS_CHARS = 500_000
LARGE_LINES = 400
LARGE_HUNK_LINES = 250
MAX_LINE_CHARS = 5000
GENERATED_TASTE = 60
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
        octal = re.match(r"[0-7]{1,3}", body[index + 1:])
        if octal:
            out.append(int(octal.group(0), 8) & 0xFF)
            index += 1 + len(octal.group(0))
            continue
        out.append(C_ESCAPES.get(body[index + 1:index + 2], ord(body[index + 1:index + 2] or "\\")))
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


def new_file(path: str, old_path: str) -> dict:
    return {"path": path, "oldPath": old_path, "status": "modified",
            "generated": bool(GENERATED.search(path)), "byName": bool(GENERATED.search(path)),
            "hunkIds": []}


def file_status(entry: dict, line: str) -> None:
    """Record a file-level header line (`new file mode`, `rename from`, `Binary files`, …)."""
    if line.startswith("new file mode"):
        entry["status"] = "added"
    elif line.startswith("deleted file mode"):
        entry["status"] = "deleted"
    elif line.startswith("rename from "):
        entry["status"] = "renamed"
        entry["oldPath"] = unquote(line[len("rename from "):])
    elif line.startswith("rename to "):
        entry["path"] = unquote(line[len("rename to "):])
    elif line.startswith("Binary files "):
        entry["status"] = "binary"


def open_hunk(line: str, header: re.Match, current: dict, hunks: list[dict]) -> dict:
    """The hunk a `@@ … @@` line starts, numbered in diff order."""
    old_no, new_no = int(header.group(1)), int(header.group(3))
    hunk = {
        "id": f"h{len(hunks) + 1}",
        "file": current["path"],
        "oldFile": current["oldPath"],
        "header": line[:line.index("@@", 2) + 2],
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
        header = {"binary": "(binary file)", "renamed": "(renamed, no content change)"}.get(
            entry["status"], "(no textual changes)"
        )
        hunk = {"id": f"h{len(hunks) + 1}", "file": entry["path"], "oldFile": entry["oldPath"],
                "header": header, "context": "", "oldStart": 0, "newStart": 0,
                "additions": 0, "deletions": 0, "lines": []}
        hunks.append(hunk)
        entry["hunkIds"].append(hunk["id"])


def parse(diff: str) -> dict:
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

        if hunk is None or not line[:1] in " +-\\":
            file_status(current, line)

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


def apply_limits(files: list[dict], hunks: list[dict]) -> None:
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


def index_markdown(parsed: dict) -> str:
    """The hunk index alone: ids, files, changed-line ranges, and size flags.

    This is the compact reference a persona package carries alongside the diff. It orientates
    without re-quoting lines the package already holds, so it costs tens of lines instead of a
    second copy of the patch. Each id carries its new-file start line and span, because a persona
    citing an id in a multi-hunk file otherwise has no way to confirm which hunk a finding belongs
    to, and the coverage gate accepts any real id.
    """
    by_id = {hunk["id"]: hunk for hunk in parsed["hunks"]}
    out = [f"# Hunk index ({len(parsed['hunks'])} hunks in {len(parsed['files'])} files)\n"]
    for entry in parsed["files"]:
        flags = [entry["status"] if entry["status"] != "modified" else "",
                 "likely-generated" if entry["generated"] else "",
                 "diff-too-large" if entry.get("suppressed") else ""]
        ids = ", ".join(
            f"{hunk_id} @{by_id[hunk_id]['newStart']}"
            f"(+{by_id[hunk_id]['additions']}/-{by_id[hunk_id]['deletions']})"
            for hunk_id in entry["hunkIds"])
        label = f" [{', '.join(f for f in flags if f)}]" if any(flags) else ""
        out.append(f"- `{entry['path']}`{label}: {ids}")
    return "\n".join(out)


def markdown(parsed: dict) -> str:
    """Hunk index plus bodies, in the shape the layer-mapping pass reads."""
    by_id = {hunk["id"]: hunk for hunk in parsed["hunks"]}
    out = [index_markdown(parsed), "\n# Hunks\n"]
    for entry in parsed["files"]:
        suffix = f" (renamed from {entry['oldPath']})" if entry["status"] == "renamed" else ""
        if entry["status"] not in {"modified", "renamed"}:
            suffix = f" ({entry['status']})"
        out.append(f"\n## FILE {entry['path']}{suffix}\n")
        for hunk_id in entry["hunkIds"]:
            hunk = by_id[hunk_id]
            context = f" {hunk['context']}" if hunk["context"] else ""
            out.append(f"### {hunk_id} — {hunk['header']}{context}")
            if hunk.get("suppressed"):
                note = ", almost certainly generated" if entry["generated"] else ""
                out.append(f"(+{hunk['additions']}/-{hunk['deletions']}: diff too large to include"
                           f"{note}. Read it only if it matters.)")
            elif hunk["lines"]:
                shown = hunk["lines"][:GENERATED_TASTE] if entry["generated"] else hunk["lines"]
                out.append("```diff")
                for line in shown:
                    more = f" …({line['cut'] - len(line['s'])} more chars)" if line.get("cut") else ""
                    out.append(f"{line['t']}{line['s']}{more}")
                out.append("```")
                if len(shown) < len(hunk["lines"]):
                    out.append(f"({len(hunk['lines']) - len(shown)} more lines of a likely generated "
                               "file omitted)")
            out.append("")
    return "\n".join(out)


def package_diff(diff: str, parsed: dict) -> str:
    """The diff a persona package embeds: generated files keep their headers, not their bodies.

    A lockfile or snapshot hunk costs every persona its full size and carries no reviewable
    intent. Each generated file's hunks collapse to one note naming its ids, so the file stays
    citable and the Reading map's "lines omitted" bullet still matches what the persona sees.
    Only a filename match (`byName`) collapses: the content heuristic that also sets `generated`
    fires on any long-lined prompt or JSON file, which is exactly what a review must read.
    """
    by_id = {hunk["id"]: hunk for hunk in parsed["hunks"]}
    out: list[str] = []
    file_index = -1
    skipping = False
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            file_index += 1
            skipping = False
        elif (not skipping and 0 <= file_index < len(parsed["files"])
                and parsed["files"][file_index]["byName"] and HUNK_HEADER.match(line)):
            entry = parsed["files"][file_index]
            added = sum(by_id[i]["additions"] for i in entry["hunkIds"])
            removed = sum(by_id[i]["deletions"] for i in entry["hunkIds"])
            out.append(f"# {entry['path']}: likely generated, +{added}/-{removed} lines omitted "
                       f"({', '.join(entry['hunkIds'])}); read it only if it matters")
            skipping = True
        if not skipping:
            out.append(line)
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split a unified diff into numbered hunks for the reviewer layer map.")
    parser.add_argument("diff", type=Path, help="unified diff file, or - for stdin")
    parser.add_argument("--out", type=Path, required=True,
                        help="directory for hunks.json, hunks.md, hunks.index.md, and package.diff")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help="bound the printed JSON summary")
    args = parser.parse_args()

    if str(args.diff) == "-":
        text = sys.stdin.read()
        origin = "stdin"
    else:
        try:
            text = args.diff.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            print(f"review-hunks: {error}", file=sys.stderr)
            return 2
        origin = str(args.diff)
    if not text.strip():
        print(f"review-hunks: {origin} is empty; there is no diff to map", file=sys.stderr)
        return 2
    if "diff --git " not in text and not HUNK_HEADER.search(text.split("\n")[0]):
        print(f"review-hunks: {origin} is not a unified diff (no `diff --git` line)", file=sys.stderr)
        return 2

    parsed = parse(text)
    if not parsed["hunks"]:
        print(f"review-hunks: {origin} contains no hunks", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "hunks.json").write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    (args.out / "hunks.md").write_text(markdown(parsed), encoding="utf-8")
    (args.out / "hunks.index.md").write_text(index_markdown(parsed) + "\n", encoding="utf-8")
    (args.out / "package.diff").write_text(package_diff(text, parsed), encoding="utf-8")
    omitted = [entry["path"] for entry in parsed["files"] if entry["byName"]]
    heuristic = [entry["path"] for entry in parsed["files"] if entry["generated"] and not entry["byName"]]
    summary = {"hunks": len(parsed["hunks"]), "files": len(parsed["files"]),
               "omitted": omitted, "keptDespiteContentFlag": heuristic, "out": str(args.out)}
    print(bounded_json(summary, args.max_chars, what="hunk summary"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
