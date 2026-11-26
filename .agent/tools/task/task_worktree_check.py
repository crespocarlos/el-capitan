"""`crew-progress.py worktree check <tree>`: may `crew implement` cut a branch in this checkout?

Step 4 of `crew-implement` branches off the default branch in the current checkout. Two cases must not
do that, and the answer is computed here, not left to prose:

    on-feature-branch  exit 4  the tree is already on a non-default branch: use it as-is, cut nothing
                               (unless the user asks for a new branch)
    dirty              exit 5  uncommitted changes other than the task's own files: switching or
                               creating a branch could carry or lose them; stop and ask once
    ok                 exit 0  on the default branch (or detached) and clean: cut the branch

The branch test comes first: staying on the branch changes nothing, so a dirty tree there is fine. The
task's own files are `.crew-worker.lock` and anything under `--task-dir` (when it sits inside the tree).

    crew-progress.py worktree check <tree> [--task-dir DIR] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.git import GitError, base_ref, current_branch, dirty_files, toplevel

EXIT = {"ok": 0, "on-feature-branch": 4, "dirty": 5}
OWN_FILES = (".crew-worker.lock",)


def default_names(root: Path) -> set[str]:
    """The default branch's name from the local remote HEAD, plus `main` and `master`."""
    base = base_ref(root)
    return {"main", "master"} | ({base.split("/", 1)[1]} if "/" in base else set())


def own_path(path: str, root: Path, task_dir: Path | None) -> bool:
    if path in OWN_FILES:
        return True
    if task_dir is None:
        return False
    try:
        rel = task_dir.resolve().relative_to(root).as_posix()
    except ValueError:
        return False
    return path == rel or Path(path).is_relative_to(rel)


def foreign_changes(root: Path, task_dir: Path | None) -> list[str]:
    """Changed paths that are not the task's own files."""
    paths = [line[3:].split(" -> ")[-1].strip('"') for line in dirty_files(root)]
    return [p for p in paths if not own_path(p, root, task_dir)]


def check(root: Path, task_dir: Path | None) -> tuple[str, str]:
    """`(state, detail)`: the state is a key of `EXIT`."""
    try:
        branch = current_branch(root)
    except GitError:
        branch = ""  # detached: nothing to keep, so the dirty test decides
    if branch and branch not in default_names(root):
        return "on-feature-branch", branch
    changed = foreign_changes(root, task_dir)
    return ("dirty", ", ".join(changed[:5])) if changed else ("ok", branch)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="crew-progress.py worktree check", description=__doc__.split("\n\n")[0])
    parser.add_argument("tree", type=Path)
    parser.add_argument("--task-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        state, detail = check(toplevel(args.tree), args.task_dir)
    except GitError as error:
        print(f"worktree: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"state": state, "detail": detail}) if args.json else state)
    return EXIT[state]
