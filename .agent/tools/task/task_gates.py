#!/usr/bin/env python3
"""The status transitions and their evidence gates: approve, implement, and close out.

DRAFTING→APPROVED refuses an unresolved clarification and an unapprovable `## Tests` block.
IMPLEMENTING→DONE means a PR is open: `mark-done` records it in the task's PR list (several allowed)
and refuses an unchecked criterion or a reviewed commit that is not an ancestor of HEAD; the verdict
and the PR's branch do not decide it. The messages are the contract hooks and skills read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_progress import GITHUB_PR_URL, append_pr
from task_state import (
    PREDICATES,
    TaskState,
    head,
    load,
    name,
    set_status,
    unresolved,
)
from task_status import review_file, reviewed_at, typed_tests_problem
from task_worktrees import default_names

from lib.files import atomic_write
from lib.git import GitError, current_branch, head_sha, is_ancestor, remote_url, slug_from_url, toplevel


def load_task(task_dir: str | Path) -> TaskState | None:
    if not (Path(task_dir) / "SPEC.md").is_file():
        print(f"error: no SPEC.md in {task_dir}", file=sys.stderr)
        return None
    return load(Path(task_dir))


def mark_approved(task_dir: str | Path) -> int:
    """Gate 1: the user approved the spec. Only DRAFTING can be approved."""
    r = load_task(task_dir)
    if r is None:
        return 1
    if head(r) == "APPROVED":
        print(f"already approved: {name(r)}")
        return 0
    if head(r) != "DRAFTING":
        print(f"error: {name(r)} is {head(r) or 'unset'}, not DRAFTING; nothing written",
              file=sys.stderr)
        return 1
    if unresolved(r.text):
        print(f"error: {name(r)} still has [NEEDS CLARIFICATION] items; a spec with open items "
              f"cannot be approved", file=sys.stderr)
        return 1
    problem = typed_tests_problem(r.task / "SPEC.md")
    if problem:
        print(f"error: {name(r)}: {problem}; fix the ## Tests block before approving",
              file=sys.stderr)
        return 1
    return 0 if set_status(r, "APPROVED", "DRAFTING → APPROVED") else 1


def update_task_branch(r: TaskState, branch: str, worktree: Path | None = None) -> bool:
    """Record the branch actually being implemented, and its checkout when known, keeping the drafting branch.

    `.task-id.branch` is the resolution key, so overwriting it strands the checkout the spec was
    written in. `spec_branch` holds the drafting branch and resolution matches either; writing
    metadata before SPEC.md means an interrupt cannot leave the status advanced with no branch.
    """
    metadata_path = r.task / ".task-id"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("not an object")
        wanted = {"branch": branch, **({"worktree": str(worktree)} if worktree is not None else {})}
        if all(metadata.get(key) == value for key, value in wanted.items()):
            return True
        if metadata.get("branch") != branch and metadata.get("spec_branch") in (None, ""):
            metadata["spec_branch"] = metadata.get("branch", "")
        metadata.update(wanted)
        atomic_write(metadata_path, json.dumps(metadata, indent=2) + "\n")
        return True
    except (OSError, ValueError) as error:
        print(f"error: {name(r)}: .task-id not updated: {error}", file=sys.stderr)
        return False


def task_checkout(r: TaskState, root: Path) -> tuple[Path | None, str]:
    """`(top level, "")` when `root` is a checkout of the task's repository, else `(None, why not)`.

    Either `origin` or `upstream` (a fork's base) may be the task's remote, compared by `slug_from_url` so ssh,
    https and `.git` agree.
    """
    expected = (slug_from_url(r.meta.get("repo_remote_url")) or "").lower()
    try:
        top = toplevel(root)
        found = {(slug_from_url(remote_url(top, remote)) or "").lower() for remote in ("origin", "upstream")} - {""}
    except GitError:
        return None, f"{root} is not a git checkout"
    if not expected:
        return None, "the task records no repo_remote_url"
    if expected not in found:
        return None, f"{top} is a checkout of {', '.join(sorted(found)) or 'no GitHub remote'}, not {expected}"
    return top, ""


def on_branch(top: Path | None, branch: str) -> bool:
    """True when the checkout `top` has `branch` checked out."""
    try:
        return top is not None and current_branch(top) == branch
    except GitError:
        return False


def branch_holder(r: TaskState, branch: str) -> str:
    """The name of another task of the same repository that already records `branch`, or ""."""
    for other in sorted(r.task.parent.glob("*/SPEC.md")):
        if other.parent == r.task:
            continue
        try:
            sibling = load(other.parent)
        except (OSError, ValueError):
            continue
        if sibling.repo.lower() == r.repo.lower() and sibling.meta.get("branch") == branch:
            return name(sibling)
    return ""


def implementing_target(r: TaskState, branch: str, root: Path) -> tuple[str, Path | None] | None:
    """The branch to record and the checkout to record with it; None, said on stderr, when no branch is known.

    An explicit branch always stands, its checkout only when `root` belongs to the task's repository and holds
    it. Without one, the checkout's current branch is taken, never the default branch (where the spec was
    drafted) and never a branch another task of the repository records.
    """
    top, why = task_checkout(r, root)
    if branch:
        return branch, top if on_branch(top, branch) else None
    if top is not None:
        try:
            current = current_branch(top)
        except GitError:
            current, why = "", f"{top} has a detached HEAD"
        holder = branch_holder(r, current) if current else ""
        if current and current not in default_names(top) and not holder:
            return current, top
        why = why or (f"{current} is already the branch of {holder}" if holder
                      else f"{top} is on the default branch {current}")
    print(f"error: {name(r)}: no --branch given and {why}; pass --branch <implementing branch> or run from "
          "the implementation checkout; nothing written", file=sys.stderr)
    return None


def started(r: TaskState, root: Path) -> bool:
    """True when an IMPLEMENTING task already records a branch off the default branch, which only --branch changes."""
    recorded = r.meta.get("branch") or ""
    top, _ = task_checkout(r, root)
    defaults = default_names(top) if top is not None else {"main", "master"}
    return head(r) == "IMPLEMENTING" and bool(recorded) and recorded not in defaults


def mark_implementing(task_dir: str | Path, branch: str = "", root: Path | None = None) -> int:
    r = load_task(task_dir)
    if r is None:
        return 1
    if head(r) not in ("APPROVED", "IMPLEMENTING"):
        print(f"error: {name(r)} is {head(r) or 'unset'}, not APPROVED; nothing written",
              file=sys.stderr)
        return 1
    if head(r) == "APPROVED" and unresolved(r.text):
        print(f"error: {name(r)} still has [NEEDS CLARIFICATION] items; resolve them before "
              f"implementing", file=sys.stderr)
        return 1
    root = Path.cwd() if root is None else root
    if not branch and started(r, root):
        print(f"already implementing: {name(r)}")
        return 0
    target = implementing_target(r, branch, root)
    if target is None:
        return 2
    # Record the implementing branch first: task resolution keys on it, and writing it after the
    # status would leave an interrupt with the status advanced and no branch.
    if not update_task_branch(r, *target):
        return 1
    if head(r) == "IMPLEMENTING":
        print(f"already implementing: {name(r)}")
        return 0
    return 0 if set_status(r, "IMPLEMENTING", "APPROVED → IMPLEMENTING") else 1


def review_location(task: Path) -> str:
    """A one-line statement of which file the verdict and the reviewed commit came from.

    The gate prints it, so a refusal or an acceptance is auditable: a review found under a temp
    directory and one found beside the spec are both legitimate, and the difference matters when a
    later reader asks why a task closed.
    """
    review = review_file(task)
    if review is None:
        return "no review found (neither REVIEW.md nor the recorded review directory)"
    if review.parent == task:
        return f"review read from {review}"
    return f"review read from {review} (recorded in {task / 'run.json'})"


def ancestry_problem(reviewed_at: str) -> str | None:
    """Why the reviewed commit does not cover HEAD, or None when it is an ancestor.

    `crew commit` runs after `crew review`, so HEAD is normally one or more commits ahead of the
    reviewed tree. An unrelated or unresolvable SHA must fail rather than silently satisfy the gate:
    a git error here is reported as unverifiable, never as approval.
    """
    try:
        if is_ancestor(None, reviewed_at, "HEAD"):
            return None
        current = head_sha(None)
        return (f"review was of {reviewed_at[:12]}, which is not an ancestor of HEAD "
                f"{current[:12]}; re-run crew review")
    except GitError:
        return (f"cannot verify that review {reviewed_at[:12]} covers HEAD; "
                "run from the implementation checkout")


def done_problems(r: TaskState) -> list[str]:
    """Every reason this spec may not close out yet: unchecked criteria, then a review that does not cover HEAD."""
    problems = []
    if not (PREDICATES["all_checked"](r, None) and PREDICATES["has_checkboxes"](r, None)):
        problems.append(f"{r.open} unchecked criteria/tasks" if r.open
                        else "no checked criteria")
    review = review_file(r.task)
    commit = reviewed_at(review)
    if commit:
        problem = ancestry_problem(commit)
        if problem:
            problems.append(problem)
    elif review is not None:
        # Legacy reviews carry no identity; flag rather than block so old tasks still close.
        print(f'warning: {review} has no "Reviewed at:" commit; cannot confirm it covers HEAD',
              file=sys.stderr)
    return problems


def record_pr(r: TaskState, pr_url: str) -> None:
    """Append a valid PR URL to the task's PR list, saying so; a URL already there or a note adds nothing."""
    if not GITHUB_PR_URL.fullmatch(pr_url) or pr_url in r.prs:
        return
    try:
        append_pr(r.task, pr_url)
    except OSError as error:
        print(f"warning: {name(r)}: PR not recorded: {error}", file=sys.stderr)
        return
    print(f"recorded PR: {pr_url}")


def mark_done(task_dir: str | Path, pr_url: str, force: bool) -> int:
    """IMPLEMENTING to DONE with the PR that was opened; a DONE task only gains the PR in its list."""
    r = load_task(task_dir)
    if r is None:
        return 1
    if not GITHUB_PR_URL.fullmatch(pr_url) and not force:
        print(f"error: --pr-url {pr_url!r} is not a GitHub PR URL (https://github.com/OWNER/REPO/pull/N); "
              "nothing written (--force records a free-text note instead)", file=sys.stderr)
        return 2
    if head(r) == "DONE":
        print(f"already done: {name(r)}")
        record_pr(r, pr_url)
        return 0
    if head(r) != "IMPLEMENTING":
        print(f"error: {name(r)} is {head(r) or 'unset'}, not IMPLEMENTING; nothing written",
              file=sys.stderr)
        return 1
    problems = done_problems(r)
    if problems and not force:
        print(f"error: {name(r)}: {'; '.join(problems)}; status not changed (--force overrides)",
              file=sys.stderr)
        record_pr(r, pr_url)
        print(f"note: {review_location(r.task)}", file=sys.stderr)
        return 1
    print(f"done: {review_location(r.task)}")
    return 0 if set_status(r, "DONE", f"IMPLEMENTING → DONE (PR opened: {pr_url})") else 1
