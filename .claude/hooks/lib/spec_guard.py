#!/usr/bin/env python3
"""The task-directory half of `check-task-spec-owner.sh`: one Write, Edit or MultiEdit payload on stdin.

Usage: python3 -I spec_guard.py <tasks root>. Prints one line:
  skip            the target is not a file this guard protects (outside the tasks root, or a task file
                  other than SPEC.md and the evidence files below);
  ok <path>       a task SPEC.md (the resolved path) whose Status the write leaves alone, or a new one
                  born DRAFTING or with no Status; the shell guard goes on to its slug check;
  deny <message>  refused.
Any other outcome (a crash, no output) is a denial in the caller: this guard fails closed.

The path is decided first, with realpath and case-insensitive names, so `..`, `//`, a symlinked task
directory and `spec.md` all reach the check, and a write anywhere else never loads the Status reader.
For a task SPEC.md the reader is `task_status` (loaded by path): `spec_text` gives the universal-newline
text `read_status` sees, on both the file and what the write would leave, and `status_of` reads it. A
write that leaves more than one `## Status` heading is refused. The tool decides which fields are read
(Write: `content`; Edit: `old_string`, `new_string`, `replace_all`; MultiEdit: `edits`); a payload with
another tool's fields, an unknown tool, or an edit that does not apply exactly once is refused.
`.task-id`, PROGRESS.md and a review's or spec run's (`spec-agents/`) `*.expect`, `*.provenance.json`, `*.out.md`,
`*.prev.md` and `*.unanswered` are written only by crew tools.

`spec_guard.py --shell <tasks root>` is the path half of `guard/task-files.sh`: NUL-separated `kind` (`w` a write
target, `d` a copy destination), `cwd`, `path` triples on stdin (the literal targets a shell command writes), one
`deny <message>` line for the first protected one (`shell_verdict`), nothing otherwise.
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
# The fields each tool reads (Claude Code and Cursor name the tools alike); another tool's fields are refused.
OWN = {"Write": {"content"}, "Edit": {"old_string", "new_string", "replace_all"}, "MultiEdit": {"edits"}}
FIELDS = set().union(*OWN.values())
BORN = ("", "DRAFTING")


def reader() -> ModuleType:
    """`task_status`, loaded by path from the checkout this hook links into (it imports only the stdlib)."""
    source = Path(__file__).resolve().parents[3] / "src" / "crew" / "task" / "task_status.py"
    spec = importlib.util.spec_from_file_location("task_status", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fields_of(payload: dict) -> dict:
    """The tool's fields in either harness shape: Claude's `tool_input`, or Cursor's top-level keys."""
    inner = payload.get("tool_input")
    return {**payload, **inner} if isinstance(inner, dict) else payload


def target(fields: dict, payload: dict) -> str:
    """The resolved file path: `file_path`, else `path` or `target_file` (Cursor's Delete key is undocumented)."""
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
    """`<task>/.task-id`, `<task>/PROGRESS.md` (its gate-stamped transitions are the recorded status), or
    `<task>/review/**/<name>` or `<task>/spec-agents/**/<name>` with an evidence suffix (lowercased names)."""
    return names[1:] in ([".task-id"], ["progress.md"]) or (len(names) > 2 and names[1] in ("review", "spec-agents") and names[-1].endswith(EVIDENCE))


def spec_verdict(path: str, tool: str, fields: dict) -> str:
    """The verdict for a write to the task SPEC.md at `path`, read with the canonical reader."""
    status = reader()
    exists = os.path.exists(path)
    disk = ""
    if exists:
        with open(path, encoding="utf-8", newline="") as handle:
            disk = handle.read()
    after, reason = written(tool, fields, disk)
    if after is None:
        return f"deny Task spec guard: cannot tell what this write does to the Status of {path}: {reason}. Write the edit exactly as the file holds it."
    if len(HEADING.findall(status.spec_text(after))) > 1:
        return f"deny Task spec guard: this leaves more than one '## Status' heading in {path}; a spec has exactly one."
    before, now = status.status_of(disk), status.status_of(after)
    if not exists and now not in BORN:
        return f"deny Task spec guard: a new spec starts as DRAFTING, not '{now}' ({path}). The status moves only through {MOVES}."
    if exists and before != now:
        return f"deny Task spec guard: this changes the Status of {path} from '{before or 'none'}' to '{now or 'none'}'. The status moves only through {MOVES}; edit the rest of the spec freely."
    return f"ok {path}"


def verdict(payload: dict, tasks_root: str) -> str:
    """Decide on the path first; only an existing or new task SPEC.md loads the Status reader."""
    fields = fields_of(payload)
    path = target(fields, payload)
    root = os.path.realpath(tasks_root)
    if not path or not path.startswith(root + os.sep):
        return "skip"
    parts = os.path.relpath(path, root).split(os.sep)
    names = [part.lower() for part in parts]
    if payload.get("tool_name") == "Delete" and (names[1:] == ["spec.md"] or evidence(names)):
        return f"deny Task spec guard: {path} is a task record; only crew tools remove it."
    if evidence(names):
        return f"deny Task spec guard: {path} is task or review evidence that only crew tools write."
    if names[1:] != ["spec.md"]:
        return "skip"
    if parts[1] != "SPEC.md":
        return f"deny Task spec guard: write the task spec as SPEC.md, not {parts[1]} (on a case-insensitive disk it is the same file)."
    tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else ""
    return spec_verdict(path, tool, fields)


def shell_verdict(kind: str, path: str, cwd: str, tasks_root: str) -> str:
    """`guard/task-files.sh`: "" or `deny <message>` for one literal path a shell command writes, run in `cwd`.

    The path is decided as for a file write, `$HOME` and `${HOME}` read as the hook's HOME. An existing task SPEC.md
    or `.task-id`, PROGRESS.md and any review evidence file are refused; a SPEC.md or `.task-id` not there yet passes
    only as a task's first write, in a directory with neither a PROGRESS.md nor a `.task-id`. A `cp`/`mv`/`rsync`
    destination (`kind` "d") anywhere inside a task directory is refused, so a whole task folder is never copied over
    another. A removal (`kind` "r": `rm`, `unlink`, `find -delete`) of a protected file, a task directory, the tasks
    root or a directory above it is refused.
    """
    home = os.environ.get("HOME", "")
    for spelled in ("${HOME}", "$HOME"):
        path = path.replace(spelled, home) if home else path
    full = os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))
    root = os.path.realpath(tasks_root)
    if kind == "r" and (full == root or root.startswith(full.rstrip(os.sep) + os.sep)):
        return f"deny Task file guard: this shell command removes {full}, which holds every task's records."
    if not full.startswith(root + os.sep):
        return ""
    names = [part.lower() for part in os.path.relpath(full, root).split(os.sep)]
    if kind == "d":
        return f"deny Task file guard: this shell command copies or moves into {full}, inside a task directory that only crew tools write."
    if kind == "r" and len(names) == 1:
        return f"deny Task file guard: this shell command removes the task directory {full}."
    if kind == "r" and (names[1:] == ["spec.md"] or evidence(names)):
        return f"deny Task file guard: this shell command removes {full}, a task record only crew tools change."
    task = os.path.join(root, os.path.relpath(full, root).split(os.sep)[0])
    first = not any(os.path.exists(os.path.join(task, name)) for name in ("PROGRESS.md", ".task-id"))
    if names[1:] in (["spec.md"], [".task-id"]) and not os.path.exists(full) and first:
        return ""
    if names[1:] == ["spec.md"]:
        return f"deny Task file guard: this shell command writes {full}. Edit the spec with the Edit tool; the Status moves only through {MOVES}."
    if evidence(names):
        return f"deny Task file guard: this shell command writes {full}, evidence that only crew tools write."
    return ""


def main() -> int:
    if sys.argv[1:2] == ["--shell"]:
        # NUL-separated `kind`, `cwd`, `path` triples on stdin; the first refusal is printed, else nothing.
        fields = sys.stdin.read().split("\0")
        for kind, cwd, path in zip(fields[0::3], fields[1::3], fields[2::3]):
            found = shell_verdict(kind, path, cwd, sys.argv[2])
            if found:
                print(found)
                break
        return 0
    payload = json.loads(sys.stdin.read() or "{}")
    print(verdict(payload if isinstance(payload, dict) else {}, sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
