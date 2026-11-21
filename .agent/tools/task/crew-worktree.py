#!/usr/bin/env python3
"""Resolve or create a git worktree, pruning stale registered worktrees first."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.git import (  # noqa: E402
    GitError,
    current_branch,
    default_branch,
    fetch_remote,
    head_sha,
    output,
    run_git,
    toplevel,
)
from lib.output import DEFAULT_MAX_CHARS, truncate  # noqa: E402


def worktrees() -> list[tuple[Path, str | None]]:
    """Every registered worktree and its branch, from one porcelain listing."""
    entries, current_path, current_branch_name = [], None, None
    listing = output(None, ["worktree", "list", "--porcelain"])
    for line in listing.splitlines() + [""]:
        if line.startswith("worktree "):
            current_path = Path(line.removeprefix("worktree "))
        elif line.startswith("branch refs/heads/"):
            current_branch_name = line.removeprefix("branch refs/heads/")
        elif not line and current_path:
            entries.append((current_path, current_branch_name))
            current_path, current_branch_name = None, None
    return entries


def fetch_if_stale(git_dir: Path, dry_run: bool) -> None:
    fetch_head = git_dir / "FETCH_HEAD"
    if fetch_head.exists() and time.time() - fetch_head.stat().st_mtime < 3600:
        return
    if dry_run:
        print("dry-run: git fetch --prune --quiet", file=sys.stderr)
        return
    run_git(None, ["fetch", "--prune", "--quiet"], check=False)


def prune_stale(dry_run: bool) -> None:
    if dry_run:
        print("dry-run: git worktree prune", file=sys.stderr)
    else:
        run_git(None, ["worktree", "prune"], check=False)
    try:
        default = default_branch(None)
        git_dir = Path(output(None, ["rev-parse", "--git-dir"]))
        main_worktree = toplevel(None)
    except GitError as error:
        print(f"manage-worktree: cannot inspect this checkout: {error}", file=sys.stderr)
        return
    fetch_if_stale(git_dir, dry_run)
    # Match only the tracking field; the commit subject can contain ": gone]".
    gone_line = re.compile(r"^[*+ ]*(\S+)\s+\S+\s+(?:\([^)]*\)\s+)?\[[^\]]*: gone\]")
    gone = {match.group(1)
            for line in run_git(None, ["branch", "-vv"], check=False).stdout.splitlines()
            if (match := gone_line.match(line))}
    merged = {line.strip().lstrip("*+ ").strip()
              for line in run_git(None, ["branch", "--merged", f"origin/{default}"],
                                  check=False).stdout.splitlines()}
    for path, local_branch in worktrees():
        if not local_branch or path.resolve() == main_worktree or local_branch not in gone:
            continue
        if dry_run:
            print(f"dry-run: prune stale worktree {path} ({local_branch})", file=sys.stderr)
            continue
        removed = run_git(None, ["worktree", "remove", str(path)], check=False).returncode == 0
        if not removed:
            continue
        print(f"Pruned stale worktree: {path} ({local_branch})", file=sys.stderr)
        if local_branch not in merged:
            print(f"Kept local branch {local_branch} (remote gone, not merged). "
                  "Run `crew cleanup` to review it.", file=sys.stderr)
        elif run_git(None, ["branch", "-d", local_branch], check=False).returncode == 0:
            print(f"Deleted local branch: {local_branch}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-b", "--new-branch", action="store_true", help="create branch from BASE")
    parser.add_argument("--dry-run", action="store_true", help="print mutating actions without running them")
    parser.add_argument("--json", action="store_true", help="print the path as JSON on stdout")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"bound stdout past N chars with a marker (default {DEFAULT_MAX_CHARS})")
    parser.add_argument("branch", nargs="?", help="branch to resolve or create")
    parser.add_argument("base", nargs="?", help="base ref; required with --new-branch")
    args = parser.parse_args()
    if not args.branch:
        parser.error("branch is required")
    if args.new_branch and not args.base:
        parser.error("--new-branch requires BASE")
    if args.max_chars < 1:
        parser.error("--max-chars must be at least 1")
    return args


def emit(args: argparse.Namespace, path: str) -> None:
    """Print the resolved worktree path, as JSON under `--json`, bounded by `--max-chars`."""
    text = json.dumps({"path": path, "branch": args.branch}) if args.json else path
    print(truncate(text, args.max_chars, what="worktree path"))


def existing_worktree(args: argparse.Namespace, top: Path) -> str | None:
    """The path of the worktree already holding `args.branch`, or None when none does."""
    try:
        if current_branch(None) == args.branch:
            return str(top)
    except GitError:
        pass
    for path, branch in worktrees():
        if branch == args.branch:
            return str(path)
    return None


def target_path(args: argparse.Namespace, top: Path) -> tuple[Path | None, int]:
    """Where the new worktree goes, or the exit code that refuses to reuse an occupied path."""
    target = top.parent / "worktrees" / f"{top.name}-{args.branch.replace('/', '-')}"
    if not target.is_dir():
        return target, 0
    collision = next((branch for path, branch in worktrees() if path.resolve() == target.resolve()),
                     None)
    if collision:
        print(f"Error: {target} is already a worktree for branch '{collision}'. "
              f"Cannot reuse for '{args.branch}'.", file=sys.stderr)
        return None, 1
    return target.with_name(f"{target.name}-{head_sha(None, short=True)}"), 0


def add_command(args: argparse.Namespace, target: Path) -> list[str]:
    """The `worktree add` arguments, without the leading `git`."""
    if args.new_branch:
        return ["worktree", "add", "-b", args.branch, str(target), args.base]
    return ["worktree", "add", str(target), f"origin/{args.branch}"]


def create_worktree(args: argparse.Namespace, top: Path) -> int:
    """Add the worktree, fetching its branch first, and print where it went."""
    target, code = target_path(args, top)
    if target is None:
        return code
    command = add_command(args, target)
    if args.dry_run:
        print(f"dry-run: git {' '.join(command)}", file=sys.stderr)
        emit(args, str(target))
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    if not args.new_branch:
        try:
            fetch_remote(None, "origin", args.branch)
        except GitError as error:
            print(f"manage-worktree: {error}", file=sys.stderr)
            return 2
    created = run_git(None, command, check=False)
    if created.returncode:
        print(created.stderr.strip(), file=sys.stderr)
        return created.returncode
    emit(args, str(target.resolve()))
    return 0


def main() -> int:
    args = parse_args()
    try:
        prune_stale(args.dry_run)
        top = toplevel(None)
        found = existing_worktree(args, top)
        if found:
            emit(args, found)
            return 0
        return create_worktree(args, top)
    except GitError as error:
        print(f"manage-worktree: {error}", file=sys.stderr)
        return 2
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"manage-worktree: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
