#!/usr/bin/env python3
"""Worktree questions: what exists, what is stale, and the two mutations a prompt asks for.

A prompt that wants a repo fact asks a command, because a hand-rolled `git worktree list` reads
empty output when git fails and then acts on it. Three answers live here:

    listing     every registered worktree with its branch, whether it is merged into the default
                branch, and whether its upstream is gone
    remove      the one guarded mutation: the worktree goes first, and the branch only after it
    sync        fetch a remote branch, then check it out or create it

`remove` is the only destructive operation a prompt may ask for, so it reports which of the two
halves failed rather than returning one code for both: a refused worktree must leave its branch
alive, and a refused branch delete must not look like a refused removal.
"""
from __future__ import annotations

from pathlib import Path

from lib.git import (
    GitError,
    current_branch,
    default_branch,
    fetch_remote,
    is_ancestor,
    output,
    run_git,
    toplevel,
)

GONE = "[gone]"


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


def upstream_gone(branch: str) -> bool:
    """True when the branch tracks a remote ref that no longer exists.

    `%(upstream:track)` answers `[gone]` for exactly that case and nothing else, so a branch that
    never had an upstream is not reported as gone — deleting it would be a decision nobody made.
    """
    result = run_git(None, ["for-each-ref", "--format=%(upstream:track)", f"refs/heads/{branch}"],
                     check=False)
    return result.returncode == 0 and result.stdout.strip() == GONE


def merged_into_default(branch: str) -> bool:
    """True when `branch` is an ancestor of the default branch; an unknown default is not merged."""
    try:
        base = default_branch(None)
    except GitError:
        return False
    return is_ancestor(None, branch, f"origin/{base}")


def listing() -> list[dict]:
    """Each worktree as data: path, branch, merged, gone, and whether it is the main checkout."""
    main_worktree = toplevel(None)
    entries = []
    for path, branch in worktrees():
        entries.append({
            "path": str(path),
            "branch": branch,
            "main": path.resolve() == main_worktree,
            "merged": bool(branch) and merged_into_default(branch),
            "gone": bool(branch) and upstream_gone(branch),
        })
    return entries


def stale(entry: dict) -> bool:
    """A worktree `crew cleanup` may offer: never the main one, and gone or merged."""
    return not entry["main"] and bool(entry["branch"]) and (entry["merged"] or entry["gone"])


def fetch(remote: str = "origin") -> str:
    """Refresh the remote's refs, pruning the branches that no longer exist."""
    result = run_git(None, ["fetch", remote, "--prune", "--quiet"], check=False)
    if result.returncode:
        raise GitError(result.stderr.strip() or f"git exit {result.returncode}")
    return remote


def remove(path: Path, delete_branch: str | None = None, force_branch: bool = False) -> tuple[int, str]:
    """Remove a worktree, then its branch; `(exit code, message)` with the half that failed named.

    The worktree goes first because removing it is what makes the branch safe to delete, and the
    caller's chained form (`remove && branch -d`) must fail as a whole when either half refuses.
    """
    removed = run_git(None, ["worktree", "remove", str(path)], check=False)
    if removed.returncode:
        return removed.returncode, (removed.stderr.strip() or f"cannot remove {path}")
    if not delete_branch:
        return 0, f"removed worktree {path}"
    flag = "-D" if force_branch else "-d"
    deleted = run_git(None, ["branch", flag, delete_branch], check=False)
    if deleted.returncode:
        return deleted.returncode, (f"removed worktree {path}; kept branch {delete_branch}: "
                                    + (deleted.stderr.strip() or f"git exit {deleted.returncode}"))
    return 0, f"removed worktree {path} and branch {delete_branch}"


def sync(branch: str, remote: str = "origin") -> str:
    """Fetch `branch` and check it out here, creating it from the remote when it does not exist."""
    fetch_remote(None, remote, branch)
    try:
        if current_branch(None) == branch:
            return f"on {branch}"
    except GitError:
        pass
    exists = run_git(None, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                     check=False).returncode == 0
    arguments = ["checkout", branch] if exists else ["checkout", "-b", branch, f"{remote}/{branch}"]
    checked_out = run_git(None, arguments, check=False)
    if checked_out.returncode:
        raise GitError(checked_out.stderr.strip() or f"cannot check out {branch}")
    return f"on {branch}"
