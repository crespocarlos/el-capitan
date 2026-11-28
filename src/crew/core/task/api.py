"""The task verbs as typed functions: context, list, repository facts, guidance, a move, a log entry, a stage's setup,
the worker lock and ship.

Each takes typed parameters with defaults, returns a dataclass and raises `ToolError` with an enumerated code;
`crew-tool.py` builds its command line from these signatures, and an MCP server can register them unchanged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from crew.lib.errors import ToolError


@dataclass
class Prepared:
    """A stage's setup: the directory the next step works in, and one summary line."""

    work_dir: str
    summary: str


@dataclass
class Shipped:
    """A finished ship: the task (or branch), its PR, and each step as run or `<step> already done`."""

    shipped: str
    pr: str
    steps: list[str]


@dataclass
class TaskContext:
    """The task for this checkout or directory: `state` ok, or none with `task_dir` empty; the artifacts asked for."""

    state: Literal["ok", "none"]
    task_dir: str
    status: str | None = None
    slug: str | None = None
    branch: str | None = None
    remote: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    note: str = ""  # several tasks matched: which one was taken


def identity(directory: Path) -> TaskContext:
    from crew.core.task.task_status import read_status

    try:
        record = json.loads((directory / ".task-id").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ToolError("not_a_task", f"{directory} has no readable .task-id ({error})", "resolve", "pass a task directory under ~/.agent/tasks", 2) from error
    return TaskContext("ok", str(directory), read_status(directory / "SPEC.md"), record.get("slug"), record.get("branch"), record.get("repo_remote_url"))


def task_context(task_dir: str = "", branch: str = "", remote: str = "", artifacts: str = "", max_chars: int = 12_000) -> TaskContext:
    """The task for a directory, else CREW_TASK_DIR, else this checkout's repo and branch, with the artifacts asked for.

    Args:
        task_dir: this task directory
        branch: resolve for this branch instead of the checkout's
        remote: resolve for this remote URL instead of origin's
        artifacts: comma-separated: task_id, spec, progress, report, review, deferred, handoff
        max_chars: per artifact; a cut keeps the newest end of a log
    """
    from crew.core.task.task_artifacts import ARTIFACT_KEYS, artifact_texts
    from crew.core.task.task_resolve import ResolverUnavailable, best_match, matching_tasks, resolve_context

    requested = [key.strip() for key in artifacts.split(",") if key.strip()]
    unknown = sorted(set(requested) - ARTIFACT_KEYS)
    if unknown or max_chars < 1:
        raise ToolError("usage", f"unknown artifacts {unknown} or --max-chars below 1", "arguments", f"choose from {sorted(ARTIFACT_KEYS)}", 2)
    directory = task_dir or ("" if branch or remote else os.environ.get("CREW_TASK_DIR", ""))
    if directory:
        found = identity(Path(directory).expanduser())
    else:
        try:
            remote, branch = resolve_context(remote, branch)
        except ResolverUnavailable as error:
            raise ToolError("unresolved", str(error), "resolve", "check out a branch with an origin remote, or pass --task-dir", 2) from error
        matches = matching_tasks(remote, branch)
        if not matches:
            return TaskContext("none", "", remote=remote, branch=branch)
        best = best_match(matches)
        found = identity(Path(best))
        found.remote, found.branch = remote, branch
        found.note = f"{len(matches)} tasks match this repo and branch; using {best} (newest not DONE)" if len(matches) > 1 else ""
    if requested:
        found.artifacts = artifact_texts(Path(found.task_dir), requested, max_chars)
    return found


@dataclass
class TaskItem:
    """One task, compact: id, status, slug, repo, idle days, criteria done/total."""

    id: str
    status: str | None
    slug: str
    repo: str
    idle_days: int
    criteria: str


@dataclass
class Collection:
    """Items, cut at a limit with a hint naming how to get the rest: never a silent cut."""

    items: list
    returned: int
    total: int
    truncated: bool
    hint: str = ""


def collection(items: list, limit: int) -> Collection:
    kept = items[:limit]
    cut = len(kept) < len(items)
    return Collection(kept, len(kept), len(items), cut, f"{len(items) - len(kept)} more: raise --limit" if cut else "")


def task_list(repo: str = "", status: list[str] | None = None, all: bool = False, limit: int = 30) -> Collection:
    """Tasks, one compact item each, newest activity first; DONE only with `all` or a `status` naming it.

    Args:
        repo: OWNER/NAME, here, or all (default: ls.repo of ~/.agent/config.json, else here)
        status: only tasks in these states
        all: DONE tasks too
    """
    from crew.core.task.ls_data import load_rows, repo_filter, select
    from crew.core.task.task_gc import ConfigError
    from crew.core.task.task_state import head

    tasks_dir = Path.home() / ".agent" / "tasks"
    if not tasks_dir.is_dir():  # "no tasks" must not be read from a store that is not there
        raise ToolError("unavailable", f"no tasks directory {tasks_dir}", "tasks", "run install.sh", 2)
    try:
        rows = select(load_rows(tasks_dir), repo_filter(repo or None), status)
    except ConfigError as error:
        raise ToolError("config", str(error), "scope", "fix ls.repo in ~/.agent/config.json or pass --repo", 2) from error
    rows = sorted((row for row in rows if all or status or head(row) != "DONE"), key=lambda row: row.activity)
    return collection([TaskItem(row.uuid, row.status, row.slug, row.repo, row.activity, f"{row.done}/{row.done + row.open}") for row in rows], limit)


@dataclass
class RepoFacts:
    """The checkout's facts; each is None unless asked (`--field`), and the diff fields only when asked by name."""

    root: str | None = None
    branch: str | None = None
    head: str | None = None
    upstream: str | None = None
    staged: list[str] | None = None
    changed: list[str] | None = None
    staged_dirty: list[str] | None = None
    untracked: list[str] | None = None
    dirty: bool | None = None
    head_short: str | None = None
    remote: str | None = None
    remote_url: str | None = None
    remotes: dict[str, str] | None = None
    repo: str | None = None
    repo_name: str | None = None
    origin_repo: str | None = None
    default_branch: str | None = None
    diff_base: str | None = None
    fork_point: str | None = None
    diff_source: str | None = None
    changed_files: list[str] | None = None
    diff_stat: str | None = None
    diff: str | None = None


def repo_facts(field: str = "", root: str = "", remote: str = "", network: bool = False, files: list[str] | None = None) -> RepoFacts:
    """Root, branch, files, remotes, default branch and the review diff, each read only when asked.

    Args:
        field: the one fact to read (default: every one but the diff fields)
        root: the checkout to read (default: the current one)
        remote: the remote to report (default: upstream, else origin)
        network: resolve default_branch over the network (gh, then git)
        files: narrow the diff fields to these paths
    """
    from crew.core.task.task_repo_facts import DEFAULT, FIELDS, Facts, NothingToReview
    from crew.lib.git import GitError

    if field and field not in FIELDS:
        raise ToolError("usage", f"no field {field}", "arguments", f"choose from {', '.join(FIELDS)}", 2)
    facts = Facts(Path(root) if root else None, remote, network, files)
    try:
        return RepoFacts(**facts.record((field,) if field else DEFAULT))
    except NothingToReview as error:
        raise ToolError("nothing_to_review", str(error), "diff", "review an open PR (crew review PR #N) or a spec (crew review spec)") from error
    except GitError as error:
        raise ToolError("not_a_repo", str(error), "repo", "run inside a git checkout, or pass --root", 2) from error


@dataclass
class Guidance:
    """The guidance files from the root to each path, ranked and capped for `kind` unless `full`."""

    files: dict[str, str]
    note: str = ""


def guidance(paths: list[str], root: str = "", kind: str = "builder", full: bool = False) -> Guidance:
    """The AGENTS.md (else CLAUDE.md) files from the checkout root to each path, ranked and capped for `kind`.

    Args:
        paths: the files or folders the work touches
        root: the checkout the paths belong to (default: the current one)
        kind: whose cap and ranking apply (builder, reviewer-<lens>, specwriter, ...)
        full: every guidance file whole, uncapped
    """
    from crew.core.task.task_guidance import collect, repo_root
    from crew.core.task.task_guidance_kinds import kinds, narrow

    if kind not in kinds():
        raise ToolError("usage", f"unknown kind {kind}", "arguments", f"choose from {', '.join(kinds())}", 2)
    try:
        checkout = repo_root(Path(root) if root else None)
    except (OSError, ValueError) as error:
        raise ToolError("not_a_repo", str(error).strip(), "root", "run from the checkout, or pass --root", 2) from error
    record = collect(checkout, [Path(path) for path in paths])
    if all("error" in target for target in record["targets"]):
        raise ToolError("unresolved", "no target resolved", "paths", "pass paths inside the checkout")
    if full:
        return Guidance(record["files"])
    files, note = narrow(kind, record["files"], [os.path.relpath(Path(path).resolve(), checkout) for path in paths])
    return Guidance(files, note)


@dataclass
class Done:
    """What a write did, in one line (empty when it said nothing)."""

    said: str = ""


def task_transition(
    move: Literal["approve", "implement", "done", "block"], task_dir: Path, branch: str = "", root: str = "", pr_url: str = "", reason: str = ""
) -> Done:
    """One gated move of a task's state: approve (Gate 1), implement, done (a PR is open), or block (a PROGRESS line).

    Args:
        move: approve, implement, done or block
        branch: implement: the branch being implemented
        root: implement and done: the implementation checkout (default: the current one)
        pr_url: done: the PR
        reason: block: what the task waits on
    """
    from crew.core.task.task_gates import mark_approved, mark_done, mark_implementing
    from crew.core.task.task_lock import blocked

    checkout = Path(root) if root else None
    if move == "approve":
        return Done(mark_approved(task_dir))
    if move == "implement":
        return Done(mark_implementing(task_dir, branch, checkout))
    if move == "done":
        return Done(mark_done(task_dir, pr_url, root=checkout))
    return Done(blocked(task_dir, reason))


@dataclass
class Logged:
    """The PROGRESS entry written; a `stage_end` metric also carries its cost line."""

    logged: Literal["step", "metric"]
    cost: str = ""


def task_log(task_dir: Path, step: str = "", metric: list[str] | None = None) -> Logged:
    """Append one PROGRESS entry: a pipeline step ("IMPLEMENTING → REVIEW", never a status) or a metric.

    Args:
        step: a pipeline step; a status changes only through task-transition
        metric: EVENT [KEY=VALUE ...]: stage_start, stage_end, agent_end, review, commit, ...
    """
    from crew.core.task.task_progress import append_metric, append_transition, cost_line, fields
    from crew.core.task.task_record import forged_transition

    if not task_dir.is_dir():
        raise ToolError("not_a_task", f"no task directory {task_dir}", "arguments", "pass the TASK_DIR from task-context", 2)
    if bool(step) == bool(metric):
        raise ToolError("usage", "give --step or --metric, one of them", "arguments", exit=2)
    if step:
        found = [forged_transition(step)]
        found += [f"{name}: {why}" for name in ("CREW_WORKFLOW", "CREW_MEMBER") if (why := forged_transition(os.environ.get(name, ""), env=True))]
        refused = next((why for why in found if why), "")
        if refused:
            raise ToolError("refused", f"refused: {refused}; nothing written", "step", "a status changes only through task-transition", 2)
        append_transition(task_dir, step)
        return Logged("step")
    words = metric or []
    try:
        append_metric(task_dir, " ".join(words))
    except ValueError as error:
        raise ToolError("usage", str(error), "metric", "see crew-tool.py task-log --help") from error
    return Logged("metric", cost_line(fields(words)) if words[0] == "stage_end" else "")


def task_prepare(
    stage: Literal["implement", "spec"],
    task_dir: str = "",
    where: Literal["", "worktree", "here"] = "",
    branch: str = "",
    slug: str = "",
    bug: bool = False,
    paths: list[str] | None = None,
) -> Prepared:
    """A stage's setup in one call: the worker's checkout and prompts (implement), or a new task and its explorer prompt (spec).

    Args:
        stage: implement or spec
        task_dir: implement: the task
        where: implement: worktree or here, where the worker runs
        branch: implement: default the spec's `## Branch:`
        slug: spec: lowercase, hyphens
        bug: spec: the bug template
        paths: spec: files the request names
    """
    from crew.core.task.task_prepare import prepare_implement
    from crew.core.task.task_prepare_spec import prepare_spec

    if stage == "spec":
        if not slug:
            raise ToolError("usage", "spec needs --slug", "arguments", exit=2)
        return prepare_spec(slug, bug, paths)
    if not task_dir:
        raise ToolError("usage", "implement needs TASK_DIR", "arguments", exit=2)
    return prepare_implement(Path(task_dir), where, branch)


@dataclass
class Locked:
    """The lock file, and whether it is there now."""

    lock: str
    held: bool


def task_lock(action: Literal["write", "remove"], tree: Path, task: str) -> Locked:
    """Write or remove the worker lock on a tree; another task's live lock refuses both.

    Args:
        action: write (at dispatch) or remove (the builder's last step)
        tree: the worker's checkout
        task: the task the worker runs
    """
    from crew.core.task.task_lock import LOCK_NAME, remove_lock, write_lock

    if not tree.is_dir():
        raise ToolError("unavailable", f"no such directory: {tree}", "lock", exit=1)
    if action == "write":
        return Locked(str(write_lock(tree, task)), True)
    remove_lock(tree, task)
    return Locked(str(tree / LOCK_NAME), False)


def task_ship(title: str, body_file: Path, base: str, repo: str, task_dir: str = "", phase: bool = False, attribution: str = "") -> Shipped:
    """After the owner's go: commit (after the credential scan), merge the base, re-test, push, open a draft PR, mark done.

    Args:
        title: the commit message and the PR title
        body_file: the PR description
        base: the base branch approved at Gate 2
        repo: the owner/repo the PR targets, approved at Gate 2
        task_dir: the task (default: none: ship the current checkout's branch, no mark-done)
        phase: one PR of a program: record the PR, keep IMPLEMENTING
        attribution: the commit's trailer line
    """
    from crew.core.task.task_ship import ship_task

    if phase and not task_dir:
        raise ToolError("usage", "--phase needs TASK_DIR", "arguments", exit=2)
    return ship_task(Path(task_dir) if task_dir else None, title, body_file, base, repo, attribution, phase)
