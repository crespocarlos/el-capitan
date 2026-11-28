#!/usr/bin/env python3
"""The task-directory rules of `check-task-spec-owner.sh`: one normalised Write, Edit, MultiEdit or Delete event on stdin.

Usage: python3 -I spec_guard.py <tasks root>. Prints one line:
  skip                   no objection;
  deny <rule> <message>  refused by `rule` (its off switch is `EL_CAPITAN_GUARD_<RULE>`).

Rules, decided on the resolved path first (realpath, names compared case-insensitively), so a write anywhere else
never loads the Status reader:
  spec-owner  a task SPEC.md whose title neither equals nor extends the slug its `.task-id` records, over an existing
              spec whose Status is past DRAFTING: a reused directory that would overwrite a finished task's spec. While
              a spec is DRAFTING its title is the author's to change; `mark-approved` records the approved title's slug;
  task-files  a Delete of a task SPEC.md, PROGRESS.md, `.task-id` or review evidence.
  status      an Edit, MultiEdit or Write that changes the `## Status` value of an existing task SPEC.md as
              `task_status` reads it, leaves a second `## Status` heading, or cannot be applied exactly; a new SPEC.md
              whose Status is anything but empty or DRAFTING.

`spec_guard.py --shell <tasks root>`: NUL-separated `cwd`, `path` pairs on stdin (what an `rm`, `unlink` or
`find -delete` removes), one `deny <message>` line for the first task record, task directory, tasks root or directory
above it, nothing otherwise.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType

HEADING = re.compile(r"^## Status[ \t]*$", re.M)
MOVES = "crew-task.py mark-approved | mark-implementing | mark-done"
EVIDENCE = (".expect", ".provenance.json", ".out.md", ".prev.md", ".unanswered")
# The fields each tool reads; another tool's fields are refused.
OWN = {"Write": {"content"}, "Edit": {"old_string", "new_string", "replace_all"}, "MultiEdit": {"edits"}}
FIELDS = set().union(*OWN.values())
BORN = ("", "DRAFTING")


def reader() -> ModuleType:
    """`task_status` (stdlib only), loaded by path: the copy install wrote beside this file, else the checkout's."""
    here = Path(__file__).resolve()
    source = next(path for path in (here.parent / "task_status.py", here.parents[3] / "src" / "crew" / "task" / "task_status.py") if path.is_file())
    spec = importlib.util.spec_from_file_location("task_status", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fields_of(payload: dict) -> dict:
    """The tool's fields: the event's `input`."""
    inner = payload.get("input")
    return inner if isinstance(inner, dict) else {}


def target(fields: dict, payload: dict) -> str:
    """The resolved file path: `file_path`, else `path` or `target_file` (a Delete's key is undocumented)."""
    path = next((fields[key] for key in ("file_path", "path", "target_file") if fields.get(key)), "")
    if not isinstance(path, str) or not path:
        return ""
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))


def apply_edits(text: str, edits: list) -> tuple[str, str]:
    """`text` after each edit in order, as the Edit tool applies it, or ("", reason) when one cannot apply exactly."""
    for edit in edits:
        if not isinstance(edit, dict):
            return "", "an edit is not an object"
        old, new = edit.get("old_string"), edit.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            return "", "an edit has no old_string or new_string"
        count = text.count(old)
        if count == 0:
            return "", "its old_string does not occur in the file exactly as written"
        if edit.get("replace_all") is True:
            text = text.replace(old, new)
        elif count > 1:
            return "", "its old_string occurs more than once and replace_all is not set"
        else:
            text = text.replace(old, new, 1)
    return text, ""


def written(tool: str, fields: dict, disk: str) -> tuple[str | None, str]:
    """The file's text after the write, read from the tool's own fields, or (None, reason)."""
    if tool not in OWN:
        return None, f"the tool {tool or '(unnamed)'} is not one this guard reads"
    stray = sorted((FIELDS - OWN[tool]) & set(fields))
    if stray:
        return None, f"a {tool} payload carries another tool's fields ({', '.join(stray)})"
    if tool == "Write":
        content = fields.get("content")
        return (content, "") if isinstance(content, str) else (None, "the Write has no content")
    edits = fields.get("edits") if tool == "MultiEdit" else [fields]
    if not isinstance(edits, list):
        return None, "the MultiEdit has no edits list"
    text, reason = apply_edits(disk, edits)
    return (None, reason) if reason else (text, "")


def evidence(names: list[str]) -> bool:
    """`<task>/.task-id`, `<task>/PROGRESS.md`, or `<task>/review/**/<name>` or `<task>/spec-agents/**/<name>` with an
    evidence suffix (lowercased names)."""
    return names[1:] in ([".task-id"], ["progress.md"]) or (len(names) > 2 and names[1] in ("review", "spec-agents") and names[-1].endswith(EVIDENCE))


def owner_verdict(path: str, fields: dict, status: ModuleType, before: str | None) -> str:
    """spec-owner: the title this write gives the spec (its first line, `# Spec: ...`) against the recorded slug; a spec
    not there yet (`before` None) has nothing to lose."""
    text = next((fields[key] for key in ("content", "new_string") if isinstance(fields.get(key), str) and fields[key]), "")
    first = text.split("\n", 1)[0]
    if before in (None, "DRAFTING") or not first.startswith("# "):
        return "skip"
    try:
        owner = status.title_slug(json.loads(Path(path).with_name(".task-id").read_text(encoding="utf-8")).get("slug") or "")
    except (OSError, ValueError, AttributeError):
        return "skip"
    claim = status.title_slug(re.sub(r"^# +(Spec: *)?", "", first))
    if not owner or claim == owner or claim.startswith(owner + "-") or owner.rstrip("-") == claim:
        return "skip"
    return (
        f"deny spec-owner Task spec guard: {Path(path).parent} belongs to '{owner}', and the spec being written is titled '{claim}'. "
        "Writing it here overwrites another task's spec, and task directories are outside version control. "
        "Generate a new task directory (Step 1 of the specwriter protocol) instead of reusing this one."
    )


def status_verdict(path: str, tool: str, fields: dict, status: ModuleType, disk: str, exists: bool) -> str:
    """status: what the write does to the spec's `## Status`, read with the canonical reader."""
    after, reason = written(tool, fields, disk)
    if after is None:
        return f"deny status Task spec guard: cannot tell what this write does to the Status of {path}: {reason}. Write the edit exactly as the file holds it."
    if len(HEADING.findall(status.spec_text(after))) > 1:
        return f"deny status Task spec guard: this leaves more than one '## Status' heading in {path}; a spec has exactly one."
    before, now = status.status_of(disk), status.status_of(after)
    if not exists and now not in BORN:
        return f"deny status Task spec guard: a new spec starts as DRAFTING, not '{now}' ({path}). The status moves only through {MOVES}."
    if exists and before != now:
        return f"deny status Task spec guard: this changes the Status of {path} from '{before or 'none'}' to '{now or 'none'}'. The status moves only through {MOVES}; edit the rest of the spec freely."
    return "skip"


def verdict(payload: dict, tasks_root: str) -> str:
    """Decide on the path first; only a task SPEC.md loads the Status reader."""
    fields = fields_of(payload)
    path = target(fields, payload)
    root = os.path.realpath(tasks_root)
    if not path or not path.startswith(root + os.sep):
        return "skip"
    names = [part.lower() for part in os.path.relpath(path, root).split(os.sep)]
    tool = payload.get("tool") if isinstance(payload.get("tool"), str) else ""
    if tool == "Delete":
        record = names[1:] == ["spec.md"] or evidence(names)
        return f"deny task-files Task spec guard: {path} is a task record; only crew tools remove it." if record else "skip"
    if names[1:] != ["spec.md"]:
        return "skip"
    status = reader()
    exists = os.path.exists(path)
    disk = ""
    if exists:
        with open(path, encoding="utf-8", newline="") as handle:
            disk = handle.read()
    found = status_verdict(path, tool, fields, status, disk, exists)
    return found if found != "skip" else owner_verdict(path, fields, status, status.status_of(disk) if exists else None)


def removal(path: str, cwd: str, tasks_root: str) -> str:
    """`deny <message>` when removing `path` (run in `cwd`, `$HOME` and `${HOME}` read as the hook's HOME) removes a
    task record, a task directory, the tasks root or a directory above it, or names a variable the guard cannot read
    while it runs inside the tasks root; "" otherwise."""
    home = os.environ.get("HOME", "")
    for spelled in ("${HOME}", "$HOME"):
        path = path.replace(spelled, home) if home else path
    full = os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))
    root = os.path.realpath(tasks_root)
    if "$" in path and (os.path.realpath(cwd) + os.sep).startswith(root + os.sep):
        return f"deny Task file guard: this shell command removes {path}, a path the guard cannot resolve, inside {root}. Name the path."
    if full == root or root.startswith(full.rstrip(os.sep) + os.sep):
        return f"deny Task file guard: this shell command removes {full}, which holds every task's records."
    if not full.startswith(root + os.sep):
        return ""
    names = [part.lower() for part in os.path.relpath(full, root).split(os.sep)]
    if len(names) == 1 or names[1:] == ["spec.md"] or evidence(names):
        return f"deny Task file guard: this shell command removes {full}, a task record only crew tools change."
    return ""


def main() -> int:
    if sys.argv[1:2] == ["--shell"]:
        fields = sys.stdin.read().split("\0")
        found = next((line for cwd, path in zip(fields[0::2], fields[1::2]) if (line := removal(path, cwd, sys.argv[2]))), "")
        if found:
            print(found)
        return 0
    payload = json.loads(sys.stdin.read() or "{}")
    print(verdict(payload if isinstance(payload, dict) else {}, sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
