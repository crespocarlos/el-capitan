#!/usr/bin/env python3
"""Emit the resolved crew task state and bounded task artifact contents."""
import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

for _dir in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent / "scripts"):
    if (_dir / "task_status.py").is_file() and str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
from task_status import read_status  # noqa: E402  shared `## Status` contract


# Third field is the truncation edge for an over-budget artifact: `tail` keeps the newest
# content for append-only logs and for reports whose identity fields are appended last.
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


def resolve_task(args):
    """Return (resolved task JSON, exit code).

    `--task-dir`, then the cached `CREW_TASK_DIR`, then a fresh resolution. An explicit
    `--branch` or `--remote` describes a context the cache cannot know (a PR branch, another
    worktree), so it resolves fresh instead of reusing the cache.
    """
    directory = args.task_dir or (
        os.environ.get("CREW_TASK_DIR", "") if not (args.branch or args.remote) else ""
    )
    if directory:
        path = Path(directory).expanduser()
        if not (path / ".task-id").is_file():
            print(f"task-context: {path} is not a task directory (no .task-id)", file=sys.stderr)
            return None, 2
        try:
            metadata = json.loads((path / ".task-id").read_text())
        except (OSError, json.JSONDecodeError) as error:
            print(f"task-context: unreadable .task-id in {path}: {error}", file=sys.stderr)
            return None, 2
        return {
            "task_dir": str(path),
            "status": read_status(path / "SPEC.md"),
            "slug": metadata.get("slug"),
            "branch": metadata.get("branch"),
            "remote": metadata.get("repo_remote_url"),
        }, 0

    command = [str(Path(__file__).with_name("resolve-task-dir.py")), "--json"]
    if args.remote:
        command.extend(["--remote", args.remote])
    if args.branch:
        command.extend(["--branch", args.branch])
    result = subprocess.run(command, capture_output=True, text=True)
    # `resolve-task-dir.py` exits 0 while warning about an ambiguous match or malformed
    # metadata. Silencing that would hide the choice this tool then acts on.
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode:
        return None, result.returncode
    try:
        return json.loads(result.stdout), 0
    except json.JSONDecodeError:
        print("task-context: resolver returned invalid JSON", file=sys.stderr)
        return None, 2


def artifact_entry(path, key, max_chars):
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


def markdown_context(context):
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
            kept = f"last {context['max_chars']}" if edges[key] == "tail" else f"first {context['max_chars']}"
            lines.append(f"\n--- task artifact: {name} (TRUNCATED: {kept} of {artifact['bytes']} bytes) ---")
        else:
            lines.append(f"\n--- task artifact: {name} ---")
        lines.append(artifact["content"])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Emit resolved crew task status and bounded task artifact contents."
    )
    parser.add_argument(
        "--task-dir", default="",
        help="Use this task directory instead of resolving one (CREW_TASK_DIR is honored too)",
    )
    parser.add_argument("--remote", default="", help="Override repository remote URL")
    parser.add_argument("--branch", default="", help="Override repository branch")
    parser.add_argument(
        "--max-chars", type=int, default=DEFAULT_MAX_CHARS,
        help=f"Maximum characters per artifact (default: {DEFAULT_MAX_CHARS})",
    )
    parser.add_argument(
        "--artifacts", default="",
        help="Comma-separated artifact keys to include (default: all)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    args = parser.parse_args()
    if args.max_chars < 1:
        parser.error("--max-chars must be at least 1")
    if args.artifacts:
        requested = [key.strip() for key in args.artifacts.split(",") if key.strip()]
        if not requested:
            parser.error("--artifacts selected no keys")
    else:
        requested = [key for _, key, _ in ARTIFACTS]
    unknown = sorted(set(requested) - ARTIFACT_KEYS)
    if unknown:
        parser.error(f"unknown artifact keys: {', '.join(unknown)}")

    resolved, exit_code = resolve_task(args)
    if exit_code:
        return exit_code
    task_dir = resolved.get("task_dir")
    context = {
        "task": {
            "found": bool(task_dir),
            "directory": task_dir,
            "slug": resolved.get("slug"),
            "status": resolved.get("status"),
            "remote": resolved.get("remote"),
            "branch": resolved.get("branch"),
        },
        "max_chars": args.max_chars,
        "artifacts": {key: {"state": "absent"} for key in requested},
    }
    if task_dir:
        directory = Path(task_dir)
        context["artifacts"] = {
            key: artifact_entry(directory / name, key, args.max_chars)
            for name, key, _ in ARTIFACTS if key in requested
        }

    print(json.dumps(context, indent=2) if args.json else markdown_context(context))
    return 0


if __name__ == "__main__":
    sys.exit(main())
