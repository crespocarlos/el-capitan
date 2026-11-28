#!/usr/bin/env python3
"""The status transitions and their evidence gates: approve, implement, close out, and `restore-status`.

Each gate first refuses a TAMPERED task (`task_state.tampered`) until `restore-status` clears it. DRAFTING→APPROVED
refuses an open clarification and an unapprovable `## Tests` block. IMPLEMENTING→DONE means a PR is open: `mark-done`
records it in the PR list and refuses an unchecked criterion or a reviewed commit not an ancestor of HEAD; the verdict
and the PR's branch do not decide it. The messages are the contract hooks and skills read.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NoReturn

from crew.core.task.task_lock import worker_tree
from crew.core.task.task_progress import GITHUB_PR_URL, append_pr
from crew.core.task.task_state import (
    PREDICATES,
    TaskState,
    head,
    load,
    name,
    record_transition,
    recorded_state,
    set_status,
    tamper_refusal,
    tampered,
    unresolved,
    write_status,
)
from crew.core.task.task_status import ACCEPTED, review_file, reviewed_at, title_slug, typed_tests_problem
from crew.core.task.task_worktrees import default_names
from crew.lib.errors import Code, ToolError
from crew.lib.files import atomic_write
from crew.lib.git import GitError, current_branch, head_sha, is_ancestor, remote_url, slug_from_url, toplevel

CLOSABLE = ("DRAFTING", "APPROVED", "IMPLEMENTING", "ON-HOLD")  # the states `mark-done --force` closes; not ABANDONED


def refuse(message: str, exit: int = 1, code: Code = "refused") -> NoReturn:
    """A gate's refusal: the message the owner's CLI prints after `error: `, and the exit it keeps."""
    raise ToolError(code, message, "gate", exit=exit)


def load_task(task_dir: str | Path, check: bool = True) -> TaskState:
    """The task; refused when there is no SPEC.md, or (with `check`) a Status crew-task did not record."""
    if not (Path(task_dir) / "SPEC.md").is_file():
        refuse(f"no SPEC.md in {task_dir}", code="not_a_task")
    r = load(Path(task_dir))
    refusal = tamper_refusal(r) if check else ""
    if refusal:
        refuse(refusal.removeprefix("error: "))
    return r


def written(ok: bool, r: TaskState, value: str, message: str = "") -> str:
    """`message` and `applied: <task> -> <value>` once a status write succeeded; the write said why on stderr when not."""
    if not ok:
        refuse(f"{name(r)}: status not written")
    return "\n".join(filter(None, (message, f"applied: {name(r)} -> {value}")))


def owner() -> bool:
    """The owner runs this command: stdin is a terminal, which an agent's shell does not give it."""
    return sys.stdin.isatty()


def restore_status(task_dir: str | Path, accept: str | None = None) -> str:
    """Clear a TAMPERED task: write the recorded status back into the spec, or with `accept` (the owner's note, in the
    owner's own terminal: `owner()` refuses it anywhere else, as the shell guard's owner-only rule does) record the
    spec's status as a stamped transition. Only a gate-stamped status is restored, or DRAFTING for a task nothing
    recorded; an untampered task is left as it is."""
    if accept is not None and not owner():
        refuse("restore-status --accept is the owner's: run it in your own terminal; nothing written", 2)
    r = load_task(task_dir, check=False)
    want = recorded_state(r)
    if not tampered(r):
        return f"not tampered: {name(r)} is {head(r) or 'unset'}, recorded {want}"
    if accept is None:
        if r.legacy and r.recorded:
            refuse(
                f"{name(r)}: {want} was recorded by a line no gate stamped, so restore-status does not write "
                "it; the owner keeps the spec's status with --accept <note> in their own terminal; nothing written",
                2,
            )
        return written(write_status(r, want, f"{head(r) or 'unset'} → {want} (restore-status)"), r, want)
    note, spec_state = " ".join(accept.split()), head(r)
    if not note or spec_state not in ACCEPTED:
        why = "--accept needs a note" if not note else f"the spec's Status {r.status or 'unset'!r} is not a status token; restore-status writes {want}"
        refuse(f"{name(r)}: {why}; nothing written", 2)
    try:
        record_transition(r, f"{want} → {spec_state} (accepted: {note})")
    except OSError as error:
        refuse(f"{name(r)}: PROGRESS.md not updated: {error}")
    return f"accepted: {name(r)} -> {spec_state}"


def mark_approved(task_dir: str | Path) -> str:
    """Gate 1: the user approved the spec. Only DRAFTING can be approved."""
    r = load_task(task_dir)
    if head(r) == "APPROVED":
        return f"already approved: {name(r)}"
    if head(r) != "DRAFTING":
        refuse(f"{name(r)} is {head(r) or 'unset'}, not DRAFTING; nothing written")
    if unresolved(r.text):
        refuse(f"{name(r)} still has [NEEDS CLARIFICATION] items; a spec with open items cannot be approved")
    problem = typed_tests_problem(r.task / "SPEC.md")
    if problem:
        refuse(f"{name(r)}: {problem}; fix the ## Tests block before approving")
    said = written(set_status(r, "APPROVED", "DRAFTING → APPROVED"), r, "APPROVED")
    # The approved title's slug becomes the task's, so the spec-owner guard accepts a title changed while drafting.
    title = re.match(r"# +(?:Spec: *)?(.+)", r.text)
    if title and r.meta.get("slug") not in (None, title_slug(title.group(1))):
        try:
            atomic_write(r.task / ".task-id", json.dumps({**r.meta, "slug": title_slug(title.group(1))}, indent=2) + "\n")
        except OSError as error:
            print(f"warning: {name(r)}: .task-id slug not updated: {error}", file=sys.stderr)
    return said


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


def implementing_target(r: TaskState, branch: str, root: Path) -> tuple[str, Path | None]:
    """The branch to record and the checkout to record with it; refused (exit 2) when no branch is known.

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
        why = why or (f"{current} is already the branch of {holder}" if holder else f"{top} is on the default branch {current}")
    refuse(f"{name(r)}: no --branch given and {why}; pass --branch <implementing branch> or run from the implementation checkout; nothing written", 2)


def started(r: TaskState, root: Path) -> bool:
    """True when an IMPLEMENTING task already records a branch off the default branch, which only --branch changes."""
    recorded = r.meta.get("branch") or ""
    top, _ = task_checkout(r, root)
    defaults = default_names(top) if top is not None else {"main", "master"}
    return head(r) == "IMPLEMENTING" and bool(recorded) and recorded not in defaults


def mark_implementing(task_dir: str | Path, branch: str = "", root: Path | None = None) -> str:
    """APPROVED to IMPLEMENTING, recording the branch and its checkout; another task's live worker in `root` refuses."""
    r = load_task(task_dir)
    if head(r) not in ("APPROVED", "IMPLEMENTING"):
        refuse(f"{name(r)} is {head(r) or 'unset'}, not APPROVED; nothing written")
    if head(r) == "APPROVED" and unresolved(r.text):
        refuse(f"{name(r)} still has [NEEDS CLARIFICATION] items; resolve them before implementing")
    root = Path.cwd() if root is None else root
    if not branch and started(r, root):
        return f"already implementing: {name(r)}"
    target = implementing_target(r, branch, root)
    if target[1] is not None:  # the task's own checkout: another task's live worker there refuses
        worker_tree(target[1], r.task.name)
    # Record the implementing branch first: task resolution keys on it, and writing it after the
    # status would leave an interrupt with the status advanced and no branch.
    if not update_task_branch(r, *target):
        refuse(f"{name(r)}: .task-id not updated")
    if head(r) == "IMPLEMENTING":
        return f"already implementing: {name(r)}"
    return written(set_status(r, "IMPLEMENTING", "APPROVED → IMPLEMENTING"), r, "IMPLEMENTING")


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


def ancestry_problem(reviewed_at: str, root: Path | None = None) -> str | None:
    """Why the reviewed commit does not cover the HEAD of `root` (default: the cwd), or None when it is an ancestor.

    The commit after `crew review` puts HEAD one or more commits ahead of the reviewed tree. An unrelated or
    unresolvable SHA must fail rather than silently satisfy the gate: a git error here is reported as
    unverifiable, never as approval.
    """
    try:
        if is_ancestor(root, reviewed_at, "HEAD"):
            return None
        current = head_sha(root)
        return f"review was of {reviewed_at[:12]}, which is not an ancestor of HEAD {current[:12]}; re-run crew review"
    except GitError:
        return f"cannot verify that review {reviewed_at[:12]} covers HEAD; run from the implementation checkout"


def done_problems(r: TaskState, root: Path | None = None) -> list[str]:
    """Every reason this spec may not close out yet: unchecked criteria, then a review that does not cover the
    HEAD of `root` (default: the cwd)."""
    problems = []
    if not (PREDICATES["all_checked"](r, None) and PREDICATES["has_checkboxes"](r, None)):
        problems.append(f"{r.open} unchecked criteria/tasks" if r.open else "no checked criteria")
    review = review_file(r.task)
    commit = reviewed_at(review)
    if commit:
        problem = ancestry_problem(commit, root)
        if problem:
            problems.append(problem)
    elif review is not None:
        # Legacy reviews carry no identity; flag rather than block so old tasks still close.
        print(f'warning: {review} has no "Reviewed at:" commit; cannot confirm it covers HEAD', file=sys.stderr)
    return problems


def record_pr(r: TaskState, pr_url: str) -> str:
    """Append a valid PR URL to the task's PR list: `recorded PR: <url>`; a URL already there or a note adds nothing."""
    if not GITHUB_PR_URL.fullmatch(pr_url) or pr_url in r.prs:
        return ""
    try:
        append_pr(r.task, pr_url)
    except OSError as error:
        print(f"warning: {name(r)}: PR not recorded: {error}", file=sys.stderr)
        return ""
    return f"recorded PR: {pr_url}"


def mark_done(task_dir: str | Path, pr_url: str, force: bool = False, root: Path | None = None) -> str:
    """IMPLEMENTING to DONE with the PR that was opened; with `--force`, DRAFTING, APPROVED, IMPLEMENTING or ON-HOLD
    to DONE, a free-text note logged as `closed: <note>`. A DONE task only gains the PR in its list. The review
    must cover the HEAD of `root` (default: the cwd)."""
    r = load_task(task_dir)
    pr_url = pr_url.strip()
    is_pr = bool(GITHUB_PR_URL.fullmatch(pr_url))
    if not is_pr and not force:
        refuse(f"--pr-url {pr_url!r} is not a GitHub PR URL (https://github.com/OWNER/REPO/pull/N); nothing written (--force records a note instead)", 2)
    note = pr_url[len("closed:") :].strip() if pr_url.lower().startswith("closed:") else pr_url
    if not note:
        refuse("--pr-url is empty; nothing written (give a PR URL or a note)", 2)
    state = head(r) or "unset"
    if state == "DONE":
        return "\n".join(filter(None, (f"already done: {name(r)}", record_pr(r, pr_url))))
    if state != "IMPLEMENTING" and not (force and state in CLOSABLE):
        refuse(f"{name(r)} is {state}, not IMPLEMENTING; nothing written{' (--force closes it)' if state in CLOSABLE else ''}")
    if is_pr and state in ("DRAFTING", "APPROVED"):
        refuse(f"{name(r)} is {state}: a PR needs an approved spec; nothing written (approve the spec first with mark-approved, or close it with a note)")
    problems = done_problems(r, root)
    if problems and not force:
        said = (f"{name(r)}: {'; '.join(problems)}; status not changed (--force overrides)", record_pr(r, pr_url), f"note: {review_location(r.task)}")
        refuse("\n".join(filter(None, said)))
    reason = f"PR opened: {pr_url}" if is_pr else f"closed: {note}"
    return written(set_status(r, "DONE", f"{state} → DONE ({reason})"), r, "DONE", f"done: {review_location(r.task)}")
