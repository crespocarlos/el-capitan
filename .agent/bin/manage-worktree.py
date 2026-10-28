#!/usr/bin/env python3
"""Resolve or create a git worktree, pruning stale registered worktrees first."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check
    )


def git_stdout(*args: str) -> str:
    return git(*args).stdout.strip()


def worktrees() -> list[tuple[Path, str | None]]:
    entries, current_path, current_branch = [], None, None
    for line in git("worktree", "list", "--porcelain").stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            current_path = Path(line.removeprefix("worktree "))
        elif line.startswith("branch refs/heads/"):
            current_branch = line.removeprefix("branch refs/heads/")
        elif not line and current_path:
            entries.append((current_path, current_branch))
            current_path, current_branch = None, None
    return entries


DEFAULT_BRANCH_HELPER = Path(__file__).resolve().with_name("default-branch.sh")


def default_branch() -> str | None:
    try:
        result = subprocess.run(
            [str(DEFAULT_BRANCH_HELPER), "--strict"],
            text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def fetch_if_stale(git_dir: Path, dry_run: bool) -> None:
    fetch_head = git_dir / "FETCH_HEAD"
    if fetch_head.exists() and time.time() - fetch_head.stat().st_mtime < 3600:
        return
    if dry_run:
        print("dry-run: git fetch --prune --quiet", file=sys.stderr)
        return
    git("fetch", "--prune", "--quiet", check=False)


def prune_stale(dry_run: bool) -> None:
    if dry_run:
        print("dry-run: git worktree prune", file=sys.stderr)
    else:
        git("worktree", "prune", check=False)
    default = default_branch()
    if not default:
        return
    git_dir = Path(git_stdout("rev-parse", "--git-dir"))
    fetch_if_stale(git_dir, dry_run)
    main_worktree = Path(git_stdout("rev-parse", "--show-toplevel")).resolve()
    # Match only the tracking field; the commit subject can contain ": gone]".
    gone_line = re.compile(r"^[*+ ]*(\S+)\s+\S+\s+(?:\([^)]*\)\s+)?\[[^\]]*: gone\]")
    gone = {
        match.group(1)
        for line in git("branch", "-vv", check=False).stdout.splitlines()
        if (match := gone_line.match(line))
    }
    merged = {
        line.strip().lstrip("*+ ").strip()
        for line in git("branch", "--merged", f"origin/{default}", check=False).stdout.splitlines()
    }
    for path, local_branch in worktrees():
        if not local_branch or path.resolve() == main_worktree or local_branch not in gone:
            continue
        if dry_run:
            print(f"dry-run: prune stale worktree {path} ({local_branch})", file=sys.stderr)
            continue
        removed = git("worktree", "remove", str(path), check=False).returncode == 0
        if removed:
            print(f"Pruned stale worktree: {path} ({local_branch})", file=sys.stderr)
            if local_branch not in merged:
                print(
                    f"Kept local branch {local_branch} (remote gone, not merged). Run `crew cleanup` to review it.",
                    file=sys.stderr,
                )
            elif git("branch", "-d", local_branch, check=False).returncode == 0:
                print(f"Deleted local branch: {local_branch}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-b", "--new-branch", action="store_true", help="create branch from BASE")
    parser.add_argument("--dry-run", action="store_true", help="print mutating actions without running them")
    parser.add_argument("branch", nargs="?", help="branch to resolve or create")
    parser.add_argument("base", nargs="?", help="base ref; required with --new-branch")
    args = parser.parse_args()
    if not args.branch:
        parser.error("branch is required")
    if args.new_branch and not args.base:
        parser.error("--new-branch requires BASE")
    return args


def main() -> int:
    args = parse_args()
    try:
        prune_stale(args.dry_run)
        top = Path(git_stdout("rev-parse", "--show-toplevel")).resolve()
        if git("branch", "--show-current", check=False).stdout.strip() == args.branch:
            print(top)
            return 0
        for path, branch in worktrees():
            if branch == args.branch:
                print(path)
                return 0
        target = top.parent / "worktrees" / f"{top.name}-{args.branch.replace('/', '-')}"
        if target.is_dir():
            collision = next((branch for path, branch in worktrees() if path.resolve() == target.resolve()), None)
            if collision:
                print(
                    f"Error: {target} is already a worktree for branch '{collision}'. Cannot reuse for '{args.branch}'.",
                    file=sys.stderr,
                )
                return 1
            target = target.with_name(f"{target.name}-{git_stdout('rev-parse', '--short', 'HEAD')}")
        if args.dry_run:
            command = ["git", "worktree", "add"]
            if args.new_branch:
                command.extend(["-b", args.branch, str(target), args.base])
            else:
                command.extend([str(target), f"origin/{args.branch}"])
            print(f"dry-run: {' '.join(command)}", file=sys.stderr)
            print(target)
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.new_branch:
            command = ["worktree", "add", "-b", args.branch, str(target), args.base]
        else:
            fetched = git("fetch", "origin", args.branch, check=False)
            if fetched.returncode:
                print(fetched.stderr.strip(), file=sys.stderr)
                return fetched.returncode
            command = ["worktree", "add", str(target), f"origin/{args.branch}"]
        created = git(*command, check=False)
        if created.returncode:
            print(created.stderr.strip(), file=sys.stderr)
            return created.returncode
        print(target.resolve())
        return 0
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"manage-worktree: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
