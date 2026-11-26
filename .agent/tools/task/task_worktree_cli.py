"""Worktree writes and the `crew-worktree.py` subcommands: create, sync, prune, list and remove.

An occupied target is refused naming its branch; a fetch that cannot reach the remote stops before
anything is created; an existing non-worktree target gets a `<name>-<short sha>` suffix. Stale
registrations are pruned (fetch skipped within the hour); `--remove` names which half failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from task_worktrees import fetch, listing, remove, stale, sync, worktrees

from lib.git import GitError, current_branch, fetch_remote, head_sha, output, run_git, toplevel
from lib.output import bounded_json, truncate


def existing_worktree(branch: str, top: Path) -> str | None:
    """The path of the worktree already holding `branch`, or None when none does."""
    try:
        if current_branch(None) == branch:
            return str(top)
    except GitError:
        pass
    for path, held in worktrees():
        if held == branch:
            return str(path)
    return None


def target_path(branch: str, top: Path) -> tuple[Path | None, int]:
    """Where the new worktree goes, or the exit code that refuses to reuse an occupied path."""
    target = top.parent / "worktrees" / f"{top.name}-{branch.replace('/', '-')}"
    if not target.is_dir():
        return target, 0
    collision = next((held for path, held in worktrees() if path.resolve() == target.resolve()),
                     None)
    if collision:
        print(f"Error: {target} is already a worktree for branch '{collision}'. "
              f"Cannot reuse for '{branch}'.", file=sys.stderr)
        return None, 1
    return target.with_name(f"{target.name}-{head_sha(None, short=True)}"), 0


def add_command(branch: str, base: str | None, target: Path) -> list[str]:
    """The `worktree add` arguments, without the leading `git`."""
    if base:
        return ["worktree", "add", "-b", branch, str(target), base]
    return ["worktree", "add", str(target), f"origin/{branch}"]


def create(branch: str, base: str | None, top: Path) -> tuple[int, str]:
    """Add the worktree, fetching its base first; `(exit code, path or error message)`.

    A base that is not `origin/<branch>` (a SHA, say) is used as given: it names a commit, not a
    remote ref, and asking the remote for it would fail a well-formed create.
    """
    target, code = target_path(branch, top)
    if target is None:
        return code, ""
    if not base or base.startswith("origin/"):
        try:
            fetch_remote(None, "origin", (base or branch).removeprefix("origin/"))
        except GitError as error:
            return 2, str(error)
    target.parent.mkdir(exist_ok=True, parents=True)
    created = run_git(None, add_command(branch, base, target), check=False)
    if created.returncode:
        return created.returncode, created.stderr.strip()
    return 0, str(target.resolve())


def fetch_if_stale(git_dir: Path, dry_run: bool) -> None:
    """Fetch when the last one is older than an hour, so a resolve costs no round trip."""
    fetch_head = git_dir / "FETCH_HEAD"
    if fetch_head.exists() and time.time() - fetch_head.stat().st_mtime < 3600:
        return
    if dry_run:
        print("dry-run: git fetch --prune --quiet", file=sys.stderr)
        return
    run_git(None, ["fetch", "--prune", "--quiet"], check=False)


def prune_stale(dry_run: bool) -> None:
    """Prune stale registrations, then remove the worktrees whose remote branch is gone.

    A gone branch that was never merged keeps its local branch: its commits exist nowhere else, so
    deleting it would discard work nobody agreed to lose.
    """
    if dry_run:
        print("dry-run: git worktree prune", file=sys.stderr)
    else:
        run_git(None, ["worktree", "prune"], check=False)
    try:
        git_dir = Path(output(None, ["rev-parse", "--git-dir"]))
        entries = listing()
    except GitError as error:
        print(f"manage-worktree: cannot inspect this checkout: {error}", file=sys.stderr)
        return
    fetch_if_stale(git_dir, dry_run)
    for entry in entries:
        if not entry["gone"] or entry["main"]:
            continue
        if dry_run:
            print(f"dry-run: prune stale worktree {entry['path']} ({entry['branch']})",
                  file=sys.stderr)
            continue
        code, message = remove(Path(entry["path"]),
                               entry["branch"] if entry["merged"] else None)
        if code:
            print(f"manage-worktree: {message}", file=sys.stderr)
            continue
        print(f"Pruned stale worktree: {entry['path']} ({entry['branch']})", file=sys.stderr)
        if not entry["merged"]:
            print(f"Kept local branch {entry['branch']} (remote gone, not merged). "
                  "Run `crew cleanup` to review it.", file=sys.stderr)
        elif "branch " in message:
            print(f"Deleted local branch: {entry['branch']}", file=sys.stderr)


def list_worktrees(args: argparse.Namespace) -> int:
    """Report every worktree, marking which ones a cleanup may offer."""
    entries = listing()
    payload = {"worktrees": entries, "stale": [entry["path"] for entry in entries if stale(entry)]}
    print(bounded_json(payload, args.max_chars, what="worktrees"))
    return 0


def remove_worktree(args: argparse.Namespace) -> int:
    """Remove a worktree and, when named, its branch; both refusals reach the caller."""
    if args.dry_run:
        print(f"dry-run: git worktree remove {args.remove}", file=sys.stderr)
        return 0
    code, message = remove(args.remove, args.branch, force_branch=args.force)
    print(message, file=sys.stdout if code == 0 else sys.stderr)
    return code


def run_operation(args: argparse.Namespace) -> int:
    """Dispatch one non-resolve operation, so `main` stays an error-handling shell."""
    if args.list:
        return list_worktrees(args)
    if args.remove is not None:
        return remove_worktree(args)
    if args.operation == "fetch":
        print(f"fetched {fetch()}")
        return 0
    print(sync(args.branch))
    return 0


def is_operation(args: argparse.Namespace) -> bool:
    """True when the invocation asks for one of the operations rather than a resolve."""
    return bool(args.list or args.remove is not None or args.operation in {"fetch", "sync"})


def worktree_path(args: argparse.Namespace, path: str) -> None:
    """Print a resolved worktree path, as JSON under `--json`, bounded by `--max-chars`."""
    text = json.dumps({"path": path, "branch": args.branch_name}) if args.json else path
    print(truncate(text, args.max_chars, what="worktree path"))


def resolve(args: argparse.Namespace) -> int:
    """Resolve an existing worktree for the branch, or create one."""
    prune_stale(args.dry_run)
    top = toplevel(None)
    found = existing_worktree(args.branch_name, top)
    if found:
        worktree_path(args, found)
        return 0
    if args.dry_run:
        print(f"dry-run: create a worktree for {args.branch_name}", file=sys.stderr)
    code, result = create(args.branch_name, args.base if args.new_branch else None, top)
    if code:
        if result:
            print(result, file=sys.stderr)
        return code
    worktree_path(args, result)
    return 0
