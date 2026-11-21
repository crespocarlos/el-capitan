#!/usr/bin/env python3
"""The status transitions and their evidence gates: approve, implement, and close out.

Each transition is a gate, not a setter: DRAFTING→APPROVED refuses an unresolved clarification and
an unapprovable `## Tests` block, and IMPLEMENTING→DONE refuses an unchecked criterion, a verdict
that is not pass or warn, a mismatched branch, and a reviewed commit that is not an ancestor of
HEAD. The messages are the contract the hooks and skills read, so they live with the gate.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
for _path in (_TOOLS_ROOT, Path(__file__).resolve().parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from lib.git import GitError, head_sha, is_ancestor  # noqa: E402
from task_state import (  # noqa: E402
    PREDICATES,
    TaskState,
    head,
    load,
    name,
    set_status,
    unresolved,
)
from task_typed_tests import typed_tests_problem  # noqa: E402

REVIEWED_AT = re.compile(r"^Reviewed at:\s*([0-9a-f]{7,40})\s*$", re.M)


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


def update_task_branch(r: TaskState, branch: str) -> bool:
    """Record the branch actually being implemented, keeping the drafting branch.

    `.task-id.branch` is the resolution key, so overwriting it strands the checkout the spec was
    written in. `spec_branch` holds the drafting branch and resolution matches either; writing
    metadata before SPEC.md means an interrupt cannot leave the status advanced with no branch.
    """
    metadata_path = r.task / ".task-id"
    tmp = metadata_path.with_name(".task-id.tmp")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("not an object")
        if metadata.get("branch") == branch:
            return True
        if metadata.get("spec_branch") in (None, ""):
            metadata["spec_branch"] = metadata.get("branch", "")
        metadata["branch"] = branch
        tmp.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        tmp.replace(metadata_path)
        return True
    except (OSError, ValueError) as error:
        tmp.unlink(missing_ok=True)
        print(f"error: {name(r)}: .task-id not updated: {error}", file=sys.stderr)
        return False


def mark_implementing(task_dir: str | Path, branch: str = "") -> int:
    r = load_task(task_dir)
    if r is None:
        return 1
    if head(r) == "IMPLEMENTING":
        print(f"already implementing: {name(r)}")
        if branch:
            update_task_branch(r, branch)
        return 0
    if head(r) != "APPROVED":
        print(f"error: {name(r)} is {head(r) or 'unset'}, not APPROVED; nothing written",
              file=sys.stderr)
        return 1
    if unresolved(r.text):
        print(f"error: {name(r)} still has [NEEDS CLARIFICATION] items; resolve them before "
              f"implementing", file=sys.stderr)
        return 1
    # Record the implementing branch first: task resolution keys on it, and writing it after the
    # status would leave an interrupt with the status advanced and no branch.
    if branch and not update_task_branch(r, branch):
        return 1
    return 0 if set_status(r, "IMPLEMENTING", "APPROVED → IMPLEMENTING") else 1


def read_reviewed_at(task: Path) -> str:
    review = task / "REVIEW.md"
    if not review.exists():
        return ""
    matches = REVIEWED_AT.findall(review.read_text(encoding="utf-8"))
    return matches[-1] if matches else ""


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


def done_problems(r: TaskState, branch: str) -> list[str]:
    """Every reason this spec may not close out yet, in the order the gates apply."""
    problems = []
    task_branch = r.meta.get("branch")
    if branch and task_branch and branch != task_branch:
        problems.append(f"task branch is {task_branch}, current branch is {branch}")
    if not (PREDICATES["all_checked"](r, None) and PREDICATES["has_checkboxes"](r, None)):
        problems.append(f"{r.open} unchecked criteria/tasks" if r.open
                        else "no checked criteria")
    if not PREDICATES["verdict_ok"](r, None):
        problems.append(f"review verdict is {r.verdict}, need pass or warn")
    reviewed_at = read_reviewed_at(r.task)
    if reviewed_at:
        problem = ancestry_problem(reviewed_at)
        if problem:
            problems.append(problem)
    elif branch:
        # Legacy reviews carry no identity; flag rather than block so old tasks still close.
        print('warning: REVIEW.md has no "Reviewed at:" commit; cannot confirm it covers HEAD',
              file=sys.stderr)
    return problems


def mark_done(task_dir: str | Path, pr_url: str, branch: str, force: bool) -> int:
    r = load_task(task_dir)
    if r is None:
        return 1
    if head(r) == "DONE":
        print(f"already done: {name(r)}")
        return 0
    if head(r) != "IMPLEMENTING":
        print(f"error: {name(r)} is {head(r) or 'unset'}, not IMPLEMENTING; nothing written",
              file=sys.stderr)
        return 1
    problems = done_problems(r, branch)
    if problems and not force:
        print(f"error: {name(r)}: {'; '.join(problems)}; nothing written (--force overrides)",
              file=sys.stderr)
        return 1
    return 0 if set_status(r, "DONE", f"IMPLEMENTING → DONE (PR opened: {pr_url})") else 1
