"""`crew-task.py record-pr`: record a PR that `gh pr create` just opened on the task it belongs to.

One payload on stdin; exactly one distinct PR URL in the output, else nothing is written. A task of the PR's repos
(`gh pr view`: base, or the fork its head owner names) already holding the URL is the match; else head `branch`, the
open match first; else the one IMPLEMENTING task whose SPEC.md `## Branch:` names it. IMPLEMENTING goes through
`mark_done`, any other match gains the PR; several, or a `spec_branch`: nothing; none: a minimal DONE task.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from crew.lib.clock import utc_stamp
from crew.lib.files import atomic_write
from crew.lib.git import GitError
from crew.task.task_gates import mark_done, on_branch, task_checkout, update_task_branch
from crew.task.task_progress import GITHUB_PR_URL, append_pr
from crew.task.task_prs import Reader, gh_read, parsed
from crew.task.task_state import TaskState, head, load, spec_branch
from crew.task.task_worktrees import worktrees

PR_CREATE = re.compile(r"(?:^|[\s;&|(])gh\s+(?:\S+\s+)*?pr\s+create\b")  # the shell hook checks the real segment
PR_URL = re.compile(GITHUB_PR_URL.pattern + r"(?![\d#/])")  # a whole PR URL: never the PR of a comment or a file link
VIEW_FIELDS = "headRefName,headRepositoryOwner,headRepository,title"
VIEW_TIMEOUT = 8.0
CLOSED = ("DONE", "ABANDONED")
MARK_DONE = "~/.agent/bin/crew-task.py mark-done {dir} --pr-url {url}"
DEFAULT_NAMES = ("main", "master")  # the hook has no checkout of the task to read its default branch from


@dataclass
class Pull:
    """What the hook knows about the PR: its URL, head branch, title, and the repos a task may record."""

    url: str
    branch: str
    title: str
    repos: list[str]  # lowercase `owner/name`: the base, then the fork the head owner names


def created_urls(payload: dict) -> list[str]:
    """The distinct PR URLs the output of a `gh pr create` command holds, in order; [] for any other command."""
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or payload.get("command") or "")
    if not PR_CREATE.search(command):
        return []
    response = payload.get("tool_response")
    if isinstance(response, dict):
        text = f"{response.get('stdout') or ''}\n{response.get('stderr') or ''}"
    else:
        text = str(response or payload.get("output") or "")
    return list(dict.fromkeys(match.group(0) for match in PR_URL.finditer(text)))


def pull(url: str, read: Reader) -> Pull | None:
    """The PR's head branch, title and candidate repos from one `gh pr view`; None when the read failed."""
    info = parsed(read, ["pr", "view", url, "--json", VIEW_FIELDS], VIEW_TIMEOUT)
    match = GITHUB_PR_URL.fullmatch(url)
    if not isinstance(info, dict) or not match or not info.get("headRefName"):
        return None
    base = match.group(1).lower()
    owner = str((info.get("headRepositoryOwner") or {}).get("login") or "").lower()
    name = str((info.get("headRepository") or {}).get("name") or base.split("/")[1]).lower()
    repos = [base] + ([f"{owner}/{name}"] if owner and f"{owner}/{name}" != base else [])
    return Pull(url, str(info["headRefName"]), str(info.get("title") or ""), repos)


def tasks_in(tasks_dir: Path, repos: list[str]) -> list[TaskState]:
    """Every readable task recorded for one of `repos`."""
    found = []
    for directory in sorted(path for path in tasks_dir.glob("*") if (path / "SPEC.md").is_file()):
        try:
            r = load(directory)
        except (OSError, ValueError):
            continue
        if r.repo.lower() in repos:
            found.append(r)
    return found


def holding(tree: Path | None, branch: str) -> Path | None:
    """The worktree of `tree`'s repository (of the cwd when None) that has `branch` checked out, or None."""
    try:
        return next((path for path, name in worktrees(tree) if name == branch), None)
    except GitError:
        return None


def branch_tree(r: TaskState, branch: str) -> Path | None:
    """Where `mark_done` checks the review against `branch`'s HEAD: the task's recorded `worktree` when it holds the
    branch, else a worktree of that checkout's repository, else one of the cwd's (the hook payload's `cwd`)."""
    recorded = r.meta.get("worktree")
    tree = Path(recorded) if isinstance(recorded, str) and recorded and Path(recorded).is_dir() else None
    if tree is not None and task_checkout(r, tree)[0] is not None:  # a reused path in another repo is not the task's
        if on_branch(tree, branch):
            return tree
        found = holding(tree, branch)
        if found is not None:
            return found
    return holding(None, branch)


def close(r: TaskState, url: str, branch: str) -> list[str]:
    """Append the PR, then run the DONE gate from the branch's worktree when one exists; its words are the output."""
    lines = [f"record-pr: {r.slug}: {'recorded PR' if append_pr(r.task, url) else 'already has'} {url}"]
    out, saved = io.StringIO(), os.getcwd()
    tree = branch_tree(r, branch)
    try:
        if tree is not None:
            os.chdir(tree)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = mark_done(r.task, url, False)
    finally:
        os.chdir(saved)
    lines += [f"record-pr: {line}" for line in out.getvalue().splitlines() if line.strip()]
    if code != 0:
        retry = MARK_DONE.format(dir=r.task, url=url)
        lines.append(f"record-pr: {r.slug} stays {head(r)}; after fixing it run: {retry}")
    return lines


def slug_of(title: str) -> str:
    """A task slug from a PR title: lowercase words joined by `-`, at most 60 characters."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].rstrip("-") or "pr"


def minimal_task(tasks_dir: Path, found: Pull, scoped: list[TaskState]) -> str:
    """A DONE task for a PR opened with no spec, in a repo that already has tasks; no gate runs.

    The remote URL is copied from a task of the same repo, the base one first, so `crew ls` groups it with them.
    """
    owner = next(r for repo in found.repos for r in scoped if r.repo.lower() == repo)
    directory = tasks_dir / str(uuid.uuid4()).upper()
    directory.mkdir(parents=True)
    meta = {
        "uuid": directory.name,
        "repo_remote_url": owner.meta["repo_remote_url"],
        "branch": found.branch,
        "slug": slug_of(found.title),
        "created_at": utc_stamp(),
    }
    atomic_write(directory / ".task-id", json.dumps(meta, indent=2) + "\n")
    title = found.title or found.url
    atomic_write(directory / "SPEC.md", f"# {title}\n\n## Status\nDONE\n\n## Summary\nRecorded by the PR hook: {found.url} was opened with no spec.\n")
    append_pr(directory, found.url)
    return f"record-pr: no task for {found.branch}; recorded {found.url} as DONE task {directory} (no spec)"


def candidates(what: str, tasks: list[TaskState], url: str) -> list[str]:
    """`nothing recorded` with one `mark-done` command per candidate task."""
    return [f"record-pr: {what}; nothing recorded. If the PR belongs to one, run:"] + [f"  {MARK_DONE.format(dir=r.task, url=url)}" for r in tasks]


def unmoved(r: TaskState) -> bool:
    """True while `.task-id` `branch` is still the drafting branch: empty, equal to `spec_branch`, or a default name."""
    branch = r.meta.get("branch") or ""
    return branch in ("", r.meta.get("spec_branch") or "", *DEFAULT_NAMES)


def place(found: Pull, tasks_dir: Path) -> list[str]:
    """Record the PR on its task: one that already holds it, else the single open `branch` match, else the single match,
    else the single IMPLEMENTING task whose SPEC.md names the branch; never on a spec branch."""
    scoped = tasks_in(tasks_dir, found.repos)
    held = [r for r in scoped if found.url in r.prs]
    if held:  # an IMPLEMENTING holder still runs the gate; `close` does not append the URL twice
        lines = []
        for r in held:
            lines += (
                close(r, found.url, found.branch) if head(r) == "IMPLEMENTING" else [f"record-pr: {r.slug} ({head(r) or 'no status'}): already has {found.url}"]
            )
        return lines
    matches = [r for r in scoped if r.meta.get("branch") == found.branch]
    chosen = [r for r in matches if head(r) not in CLOSED] or matches
    if len(chosen) > 1:
        return candidates(f"{len(chosen)} tasks match {found.repos[0]} {found.branch}", chosen, found.url)
    if chosen:
        r = chosen[0]
        if head(r) == "IMPLEMENTING":
            return close(r, found.url, found.branch)
        done = "recorded PR" if append_pr(r.task, found.url) else "already has"
        return [f"record-pr: {r.slug} ({head(r) or 'no status'}): {done} {found.url}"]
    drafted = [r for r in scoped if r.meta.get("spec_branch") == found.branch]
    if drafted:
        names = ", ".join(r.slug for r in drafted)
        return candidates(f"{found.branch} is the spec branch of {names}", drafted, found.url)
    specced = [r for r in scoped if head(r) == "IMPLEMENTING" and spec_branch(r.text) == found.branch and unmoved(r)]
    if len(specced) > 1:
        return candidates(f"{len(specced)} tasks name {found.branch} in their spec", specced, found.url)
    if specced:
        if not update_task_branch(specced[0], found.branch):
            return [f"record-pr: {specced[0].slug}: .task-id not updated to {found.branch}; nothing recorded"]
        return close(specced[0], found.url, found.branch)
    return [minimal_task(tasks_dir, found, scoped)] if scoped else []


def record(payload: dict, tasks_dir: Path, read: Reader = gh_read) -> list[str]:
    """Record the PR of one hook payload; the printed lines, empty when the payload is not a PR creation."""
    urls = created_urls(payload)
    if len(urls) > 1:
        return [
            f"record-pr: the output holds {len(urls)} PR URLs ({', '.join(urls)}); nothing recorded. Record the created one with: {MARK_DONE.format(dir='<TASK_DIR>', url='<URL>')}"
        ]
    if not urls:
        return []
    saved, cwd = os.getcwd(), payload.get("cwd")
    try:
        if isinstance(cwd, str) and Path(cwd).is_dir():
            os.chdir(cwd)
        found = pull(urls[0], read)
        if found is None:
            return [f"record-pr: cannot read {urls[0]} with gh pr view; reconcile records it at the next session start"]
        return place(found, tasks_dir)
    finally:
        os.chdir(saved)


def main(tasks_dir: Path, text: str) -> int:
    """The `record-pr` subcommand: one payload in, the outcome on stdout; exit 0 unless the payload is not JSON."""
    try:
        payload = json.loads(text or "{}")
    except ValueError:
        print("record-pr: the hook payload is not JSON; nothing recorded")
        return 2
    try:
        lines = record(payload if isinstance(payload, dict) else {}, tasks_dir)
    except (OSError, ValueError, GitError) as error:
        lines = [f"record-pr: nothing recorded: {error}; reconcile records it at the next session start"]
    for line in lines:
        print(line)
    return 0
