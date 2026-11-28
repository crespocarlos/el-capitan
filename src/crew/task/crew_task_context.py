#!/usr/bin/env python3
"""Emit the resolved crew task state and bounded task artifact contents.

This file is the argparse entry point only. Resolution comes from `task_resolve.py`, so it agrees
with `crew-resolve-task-dir.py` by construction rather than by a second copy of the `.task-id`
lookup, and the artifact reader and renderings live in `task_artifacts.py`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from crew.task.task_artifacts import ARTIFACT_KEYS, ARTIFACTS, DEFAULT_MAX_CHARS, build_context, markdown_context
from crew.task.task_resolve import ResolverUnavailable, resolve_record
from crew.task.task_status import read_status


def cached_identity(directory: str) -> tuple[dict | None, int]:
    """The record for an explicit or cached task directory, or an error naming why it is unusable."""
    path = Path(directory).expanduser()
    if not (path / ".task-id").is_file():
        print(f"task-context: {path} is not a task directory (no .task-id)", file=sys.stderr)
        return None, 2
    try:
        metadata = json.loads((path / ".task-id").read_text(encoding="utf-8"))
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


def resolve_task(args: argparse.Namespace) -> tuple[dict | None, int]:
    """Return (resolved task JSON, exit code).

    `--task-dir`, then the cached `CREW_TASK_DIR`, then a fresh resolution. An explicit `--branch`
    or `--remote` describes a context the cache cannot know (a PR branch, another worktree), so it
    resolves fresh instead of reusing the cache.
    """
    directory = args.task_dir or (os.environ.get("CREW_TASK_DIR", "") if not (args.branch or args.remote) else "")
    if directory:
        return cached_identity(directory)
    try:
        return resolve_record(args.remote, args.branch), 0
    except ResolverUnavailable as error:
        print(str(error), file=sys.stderr)
        return None, 1


def parse_artifact_selection(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str]:
    """The artifact keys this run includes, or an argparse error naming the bad input."""
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
    return requested


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit resolved crew task status and bounded task artifact contents.")
    parser.add_argument("--task-dir", default="", help="Use this task directory instead of resolving one (CREW_TASK_DIR is honored too)")
    parser.add_argument("--remote", default="", help="Override repository remote URL")
    parser.add_argument("--branch", default="", help="Override repository branch")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help=f"Maximum characters per artifact (default: {DEFAULT_MAX_CHARS})")
    parser.add_argument("--artifacts", default="", help="Comma-separated artifact keys to include (default: all)")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    requested = parse_artifact_selection(args, parser)
    resolved, exit_code = resolve_task(args)
    if exit_code:
        return exit_code
    context = build_context(resolved.get("task_dir"), resolved, requested, args.max_chars)
    print(json.dumps(context, indent=2) if args.json else markdown_context(context))
    return 0


if __name__ == "__main__":
    sys.exit(main())
