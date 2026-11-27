"""Worktree reads: what exists and is stale, whether a branch may be cut here, and where the worker runs.

`listing`: each worktree with its branch, merged or not, upstream gone or not. `check <tree>`:
`on-feature-branch` (exit 4), `dirty` (exit 5), `ok` (exit 0). `pref` prints `worktree`, `here` or
`ask` (`AGENTS.md`, then the `<git common dir>/crew-worktree` marker); `record` writes the marker once.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from task_progress import append_worktree

from lib.files import agents_setting, atomic_write
from lib.git import (
    GitError,
    base_ref,
    current_branch,
    default_branch,
    dirty_files,
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
    """A worktree a cleanup may offer: never the main one, and gone or merged."""
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


EXIT_ON_FEATURE_BRANCH = 4
EXIT_DIRTY = 5
EXIT = {"ok": 0, "on-feature-branch": EXIT_ON_FEATURE_BRANCH, "dirty": EXIT_DIRTY}
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


def check_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="crew-task.py worktree check", description=__doc__.split("\n\n")[0])
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


CHOICES = ("worktree", "here")
MARKER = "crew-worktree"


def marker_path(root: Path) -> Path:
    """The per-repo marker, under git's common directory so every worktree of the repo shares it."""
    common = output(root, ["rev-parse", "--git-common-dir"]).strip()
    return (root / common).resolve() / MARKER


def agents_choice(root: Path) -> str:
    return {"true": "worktree", "false": "here"}.get(agents_setting(root, "worktree").lower(), "")


def recorded_choice(root: Path) -> str:
    try:
        value = marker_path(root).read_text(encoding="utf-8").strip()
    except (OSError, GitError):
        return ""
    return value if value in CHOICES else ""


def choose(root: Path) -> tuple[str, str]:
    """`(choice, source)`: `worktree`, `here` or `ask`, and where it came from."""
    for source, read in (("agents", agents_choice), ("recorded", recorded_choice)):
        value = read(root)
        if value:
            return value, source
    return "ask", "none"


def record(root: Path, choice: str, task_dir: Path) -> str:
    """Write the marker and the PROGRESS.md line once; returns the choice that stands."""
    standing = recorded_choice(root)
    if standing:
        return standing
    marker = marker_path(root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(marker, choice + "\n")
    append_worktree(task_dir, choice, marker)
    return choice


def pref_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="crew-task.py worktree", description=__doc__.split("\n\n")[0],
                                     epilog="check <TREE> [--task-dir DIR] [--json]: ok (exit 0), "
                                            "on-feature-branch (exit 4) or dirty (exit 5); its own --help.")
    parser.add_argument("action", choices=("pref", "record"))
    parser.add_argument("rest", nargs="*", help="record: <worktree|here> <TASK_DIR>")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = toplevel(args.repo)
    except GitError as error:
        print(f"worktree: {error}", file=sys.stderr)
        return 2
    if args.action == "pref":
        choice, source = choose(root)
        print(json.dumps({"choice": choice, "source": source}, indent=2) if args.json else choice)
        return 0
    if len(args.rest) != 2 or args.rest[0] not in CHOICES or not Path(args.rest[1]).is_dir():
        print("worktree: record needs <worktree|here> <TASK_DIR>", file=sys.stderr)
        return 2
    print(record(root, args.rest[0], Path(args.rest[1])))
    return 0
