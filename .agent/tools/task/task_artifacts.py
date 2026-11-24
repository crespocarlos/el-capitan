#!/usr/bin/env python3
"""Bounded task artifacts: read one artifact and render the resolved task as Markdown or JSON.

Split out of `crew-task-context.py` so the entry point stays argument handling and resolution.
The truncation edge per artifact is the interesting part: append-only logs and reports whose
identity fields are appended last keep their tail, everything else keeps its head.
"""
from __future__ import annotations

import stat
from pathlib import Path

# Third field is the truncation edge for an over-budget artifact: `tail` keeps the newest content
# for append-only logs and for reports whose identity fields are appended last. `REVIEW.md` is the one
# report whose identity block is appended by `persist` *after* the findings, so tail keeps the
# decision — verdict, next step, and reviewed commit — rather than the heading it opens with.
ARTIFACTS = (
    (".task-id", "task_id", "head"),
    ("SPEC.md", "spec", "head"),
    ("PROGRESS.md", "progress", "tail"),
    ("REPORT.md", "report", "head"),
    ("REVIEW.md", "review", "tail"),
    ("DEFERRED.md", "deferred", "head"),
    ("HANDOFF.md", "handoff", "head"),
)
ARTIFACT_KEYS = {key for _, key, _ in ARTIFACTS}
DEFAULT_MAX_CHARS = 12_000


def artifact_entry(path: Path, key: str, max_chars: int) -> dict:
    """One artifact's record: absent, unreadable, or its content with a truncation note."""
    try:
        info = path.stat()
    except FileNotFoundError:
        return {"state": "absent"}
    except OSError as error:
        return {"state": "unreadable", "error": str(error)}
    if not stat.S_ISREG(info.st_mode):
        return {"state": "absent"}
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return {"state": "unreadable", "error": str(error)}
    entry = {"state": "ok", "bytes": info.st_size}
    if len(content) <= max_chars:
        entry.update(content=content, truncated=False)
        return entry
    tail = next(edge for _, name, edge in ARTIFACTS if name == key) == "tail"
    entry.update(content=content[-max_chars:] if tail else content[:max_chars],
                 truncated=True, truncated_edge="tail" if tail else "head")
    return entry


def markdown_context(context: dict) -> str:
    task = context["task"]
    if not task["found"]:
        return "Task context: no pipeline task matches this repository and branch."
    lines = [
        f"Task context: {task['slug'] or task['directory']} ({task['status'] or 'unknown'})",
        f"Task directory: {task['directory']}",
    ]
    edges = {key: edge for _, key, edge in ARTIFACTS}
    for name, key, _ in ARTIFACTS:
        if key not in context["artifacts"]:
            continue
        artifact = context["artifacts"][key]
        state = artifact["state"]
        if state == "absent":
            lines.append(f"\n--- task artifact: {name} (absent) ---")
            continue
        if state == "unreadable":
            lines.append(f"\n--- task artifact: {name} (unreadable: {artifact['error']}) ---")
            continue
        if artifact["truncated"]:
            kept = (f"last {context['max_chars']}" if edges[key] == "tail"
                    else f"first {context['max_chars']}")
            lines.append(f"\n--- task artifact: {name} (TRUNCATED: {kept} of "
                         f"{artifact['bytes']} bytes) ---")
        else:
            lines.append(f"\n--- task artifact: {name} ---")
        lines.append(artifact["content"])
    return "\n".join(lines)


def build_context(task_dir: str | None, resolved: dict, requested: list[str],
                  max_chars: int) -> dict:
    """The emitted record: the task identity, the budget, and each requested artifact."""
    context = {
        "task": {
            "found": bool(task_dir),
            "directory": task_dir,
            "slug": resolved.get("slug"),
            "status": resolved.get("status"),
            "remote": resolved.get("remote"),
            "branch": resolved.get("branch"),
        },
        "max_chars": max_chars,
        "artifacts": {key: {"state": "absent"} for key in requested},
    }
    if task_dir:
        directory = Path(task_dir)
        context["artifacts"] = {
            key: artifact_entry(directory / name, key, max_chars)
            for name, key, _ in ARTIFACTS if key in requested
        }
    return context
