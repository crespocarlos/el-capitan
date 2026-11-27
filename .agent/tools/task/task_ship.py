"""`crew-task.py ship`: stage, commit, merge the base, re-run the spec's tests, push, open a draft PR, mark done.

It runs in the task's recorded worktree against the approved `--base` and `--repo` and never asks; `--phase` (one
PR of a program) records the PR and keeps IMPLEMENTING, `--no-task` ships the current checkout. A refusal exits 2
before `stage`. Each finished step appends `SHIP: <branch> <step> <value>` to PROGRESS.md; a re-run on that branch
resumes at the first step missing or failing its re-check. A stop exits 1. It never amends or force-pushes.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from task_gates import ancestry_problem, done_problems, mark_done, task_checkout
from task_progress import GITHUB_PR_URL, append_entry, append_pr, read_entries
from task_prs import branch_urls, gh_read
from task_ship_checks import index_refusals, leaks, untracked, untracked_refusals
from task_state import TaskState, head, load, name, tampered
from task_status import review_file, reviewed_at, typed_test_commands

from lib.git import (
    GitError,
    conflicted_paths,
    current_branch,
    default_branch,
    dirty_files,
    fetch_remote,
    gh,
    head_sha,
    is_ancestor,
    output,
    remote_url,
    rev_parse,
    run_git,
    slug_from_url,
    staged_paths,
    toplevel,
    unstaged_paths,
)

STEPS = ("stage", "commit", "merge", "test", "push", "pr", "done")
COMMAND_LIMIT = 600.0  # seconds for one `## Tests` command
TOTAL_LIMIT = 1200.0  # seconds for all of them
ATTRIBUTION = "Co-Authored-By: Claude <noreply@anthropic.com>"
SPEC_BASE = re.compile(r"^## Base:[ \t]*`?([^`\s]+)`?[ \t\r]*$", re.M)
PUSH_TIMEOUT = 120
PR_TIMEOUT = 60.0


class Stop(Exception):
    """A step cannot finish; the message says what to fix before a re-run."""


@dataclass
class Ship:
    """What every step reads: the task (None with `--no-task`), the checkout, where the PR goes, the recorded steps."""

    task: TaskState | None
    tree: Path
    branch: str
    remote: str  # the remote the base is merged from: the one whose repository is `--repo`
    base: str
    target: str  # owner/repo of the PR
    owner: str  # the owner of the PR's head repository
    title: str
    body_file: Path
    attribution: str  # the commit's trailer line
    phase: bool = False  # one PR of a program: the PR is recorded and the task stays IMPLEMENTING
    recorded: dict[str, str] = field(default_factory=dict)

    @property
    def head_ref(self) -> str:
        """The branch, or `owner:branch` when the head lives in a fork of the target."""
        same = self.target.split("/")[0].lower() == self.owner.lower()
        return self.branch if same else f"{self.owner}:{self.branch}"


def merging(tree: Path) -> bool:
    """True while a merge waits for its commit."""
    return run_git(tree, ["rev-parse", "--verify", "--quiet", "MERGE_HEAD"], check=False).returncode == 0


def stage(ship: Ship) -> str:
    conflicts = conflicted_paths(ship.tree)
    if conflicts:
        raise Stop(f"unresolved conflicts in: {', '.join(conflicts)}; resolve them and re-run ship "
                   "(it commits the resolution), or run `git merge --abort`")
    new = untracked(ship.tree)
    refused = untracked_refusals(ship.tree, new)
    if refused:
        raise Stop(f"untracked files not staged: {', '.join(refused)}; delete them, add them to .gitignore, "
                   "or commit them yourself, then re-run ship")
    output(ship.tree, ["add", "--update"])
    if new:
        output(ship.tree, ["add", "--", *new])
    refused = index_refusals(ship.tree)
    if refused:
        raise Stop(f"staged files refused: {', '.join(refused)}; unstage them (`git restore --staged <file>`), "
                   "then re-run ship")
    return ""


def stage_holds(ship: Ship, _: str) -> bool:
    return not unstaged_paths(ship.tree) and not untracked(ship.tree) and not conflicted_paths(ship.tree)


def commit(ship: Ship) -> str:
    if staged_paths(ship.tree) or merging(ship.tree):
        leaked = leaks(ship.tree)
        if leaked:
            raise Stop(f"staged changes in {', '.join(leaked)} contain a credential-like token or private key; "
                       "remove it (rotate it if it was real), then re-run ship")
        result = run_git(ship.tree, ["commit", "--quiet", "-m", ship.title, "-m", ship.attribution], check=False)
        if result.returncode:
            raise Stop(f"git commit failed: {(result.stderr or result.stdout).strip()}")
    return head_sha(ship.tree)


def commit_holds(ship: Ship, value: str) -> bool:
    return bool(value) and is_ancestor(ship.tree, value, "HEAD") and not staged_paths(ship.tree) \
        and not merging(ship.tree)


def merge(ship: Ship) -> str:
    fetch_remote(ship.tree, ship.remote, ship.base)
    upstream = f"{ship.remote}/{ship.base}"
    result = run_git(ship.tree, ["merge", "--no-edit", upstream], check=False)
    if result.returncode:
        conflicts = conflicted_paths(ship.tree)
        if conflicts:
            raise Stop(f"merging {upstream} conflicts in: {', '.join(conflicts)}; resolve them and re-run ship "
                       "(it commits the resolution), or run `git merge --abort`")
        raise Stop(f"git merge {upstream} failed: {(result.stderr or result.stdout).strip()}")
    return head_sha(ship.tree)


def merge_holds(ship: Ship, _: str) -> bool:
    """True when the freshly fetched base is already in HEAD."""
    try:
        fetch_remote(ship.tree, ship.remote, ship.base)
        return is_ancestor(ship.tree, f"{ship.remote}/{ship.base}", "HEAD")
    except GitError:
        return False


def run_command(command: str, tree: Path, limit: float, log: Path) -> int | None:
    """The command's exit code, or None when it ran past `limit`. Its process group is killed on every exit path, so
    nothing it started outlives it; it runs without the `CLAUDE*` session variables."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("CLAUDE")}
    with log.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(["bash", "-c", command], cwd=tree, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=sink, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            return None
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass  # the group already ended
            process.wait()


def test(ship: Ship) -> str:
    if ship.task is None:
        return head_sha(ship.tree)
    commands = typed_test_commands((ship.task.task / "SPEC.md").read_text(encoding="utf-8"))
    logs = ship.task.task / "artifacts" / "ship"
    logs.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + TOTAL_LIMIT
    for number, command in enumerate(commands, 1):
        remaining, log = deadline - time.monotonic(), logs / f"test-{number}.log"
        if remaining <= 0:
            raise Stop(f"the {TOTAL_LIMIT:g} s limit for all tests ran out before `{command}`")
        limit = min(COMMAND_LIMIT, remaining)
        print(f"ship: running `{command}` (log: {log})")
        code = run_command(command, ship.tree, limit, log)
        if code is None:
            raise Stop(f"`{command}` ran past {limit:.2g} s and was stopped (log: {log}); fix it in a new commit")
        if code:
            raise Stop(f"`{command}` failed with exit {code} (log: {log}); fix it in a new commit, then re-run ship")
    changed = dirty_files(ship.tree)
    if changed:
        raise Stop(f"tests changed files: {', '.join(line[3:] for line in changed)}; remove them or add them to "
                   ".gitignore before re-running ship, which would otherwise commit them")
    return head_sha(ship.tree)


def test_holds(ship: Ship, value: str) -> bool:
    return value == head_sha(ship.tree)


def push(ship: Ship) -> str:
    result = run_git(ship.tree, ["push", "--quiet", "-u", "origin", f"HEAD:refs/heads/{ship.branch}"], check=False,
                     timeout=PUSH_TIMEOUT)
    if result.returncode:
        raise Stop(f"git push failed (ship never force-pushes): {(result.stderr or result.stdout).strip()}")
    return head_sha(ship.tree)


def push_holds(ship: Ship, _: str) -> bool:
    try:
        return rev_parse(ship.tree, f"refs/remotes/origin/{ship.branch}") == head_sha(ship.tree)
    except GitError:
        return False


def open_pr(ship: Ship) -> str:
    """The open PR of this head (owner and branch) when there is one, else a new draft PR."""
    existing = branch_urls(gh_read, ship.target, ship.branch, ship.owner, PR_TIMEOUT, state="open") or []
    if existing:
        print(f"ship: a PR is already open: {existing[0]}")
        return existing[0]
    created = gh("pr", "create", "--draft", "--title", ship.title, "--body-file", str(ship.body_file),
                 "--base", ship.base, "--repo", ship.target, "--head", ship.head_ref, timeout=PR_TIMEOUT)
    found = GITHUB_PR_URL.search(created.stdout)
    if created.returncode or not found:
        raise Stop(f"gh pr create failed: {(created.stderr or created.stdout).strip() or 'no PR URL printed'}")
    print(f"ship: opened {found.group(0)}")
    return found.group(0)


def pr_holds(_: Ship, value: str) -> bool:
    """True only while the recorded PR is open: a closed or merged one is opened again."""
    if not value:
        return False
    viewed = gh("pr", "view", value, "--json", "state", "--jq", ".state", timeout=PR_TIMEOUT)
    return viewed.returncode == 0 and viewed.stdout.strip() == "OPEN"


def done(ship: Ship) -> str:
    url = ship.recorded.get("pr", "")
    if ship.task is not None and mark_done(ship.task.task, url, False, root=ship.tree):
        raise Stop(f"the PR is open ({url}) but mark-done refused it (above); fix that and re-run ship")
    return ""


def done_holds(ship: Ship, _: str) -> bool:
    return ship.task is not None and head(load(ship.task.task)) == "DONE"


STEP_RUNS: dict[str, Callable[[Ship], str]] = {
    "stage": stage, "commit": commit, "merge": merge, "test": test, "push": push, "pr": open_pr, "done": done}
STEP_HOLDS: dict[str, Callable[[Ship, str], bool]] = {
    "stage": stage_holds, "commit": commit_holds, "merge": merge_holds, "test": test_holds, "push": push_holds,
    "pr": pr_holds, "done": done_holds}


def recorded_steps(task: Path, branch: str) -> dict[str, str]:
    """Each step's last recorded value on `branch` from the `SHIP:` entries of PROGRESS.md, so one phase's steps
    never stand for the next phase's on a new branch."""
    found = {}
    for entry in read_entries(task):
        words = entry.body.strip().split(" ", 2)
        if entry.kind == "SHIP" and len(words) >= 2 and words[0] == branch:
            found[words[1]] = words[2].strip() if len(words) == 3 else ""
    return found


def refusal(task: TaskState, tree: Path, phase: bool) -> str:
    """Why the close-out would refuse: with `phase`, only a review that does not cover HEAD (later phases' boxes stay
    open), else every `done_problems` reason; "" when nothing would."""
    if phase:
        commit = reviewed_at(review_file(task.task))
        problems = [problem for problem in [ancestry_problem(commit, tree) if commit else None] if problem]
        return f"{name(task)}: {problems[0]}" if problems else ""
    problems = done_problems(task, tree) if head(task) != "DONE" else []
    return f"{name(task)}: mark-done would refuse it: {'; '.join(problems)}" if problems else ""


def checkout(task_dir: Path | None) -> tuple[TaskState | None, Path] | str:
    """The task and the checkout ship runs in, or why it cannot start: no spec, a TAMPERED status, a state other than
    IMPLEMENTING or DONE, a missing worktree, another branch, or another repository."""
    if task_dir is None:
        return None, toplevel(Path.cwd())
    if not (task_dir / "SPEC.md").is_file():
        return f"no SPEC.md in {task_dir}"
    task = load(task_dir)
    if tampered(task):
        return f"{name(task)}: {tampered(task)} (crew-task.py restore-status {task.task} [--accept <note>] clears it)"
    if head(task) not in ("IMPLEMENTING", "DONE"):
        return f"{name(task)} is {head(task) or 'unset'}, not IMPLEMENTING"
    branch, recorded = task.meta.get("branch") or "", task.meta.get("worktree") or ""
    tree = Path(recorded) if recorded else None
    if tree is None or not tree.is_dir():
        return f"{name(task)}: the recorded worktree {recorded or '(none)'} is missing; run mark-implementing --root"
    actual = current_branch(tree)
    if not branch or actual != branch:
        return f"{name(task)}: {tree} is on {actual}, not the task's branch {branch or '(none recorded)'}"
    top, why = task_checkout(task, tree)
    return (task, top) if top is not None else f"{name(task)}: {why}"


def destination(task: TaskState | None, tree: Path, base: str, repo: str) -> tuple[str, str] | str:
    """`(remote, head owner)` for the approved `--base` and `--repo`, or how ship's own resolution disagrees: `--repo`
    must be origin's or upstream's repository, and `--base` the spec's `## Base:` or that remote's default branch."""
    slugs = {remote: slug_from_url(remote_url(tree, remote)) or "" for remote in ("upstream", "origin")}
    remote = next((remote for remote, slug in slugs.items() if slug and slug.lower() == repo.lower()), "")
    if not remote:
        return f"--repo {repo} is the repository of neither origin nor upstream (origin: {slugs['origin'] or 'none'})"
    named = SPEC_BASE.search(task.text) if task is not None else None
    resolved = named.group(1) if named else default_branch(tree, remote)
    if base != resolved:
        source = "the spec's ## Base:" if named else f"the default branch of {remote}"
        return f"--base {base} disagrees with {source} ({resolved})"
    return remote, (slugs["origin"] or repo).split("/")[0]


def prepare(task_dir: Path | None, title: str, body_file: Path, base: str, repo: str, attribution: str,
            phase: bool = False) -> Ship | str:
    """The ship context, or why it cannot start (exit 2)."""
    try:
        found = checkout(task_dir)
        if isinstance(found, str):
            return found
        task, tree = found
        if phase and (task is None or head(task) != "IMPLEMENTING"):
            return "--phase needs an IMPLEMENTING task" + (f"; {name(task)} is {head(task)}" if task else "")
        branch = current_branch(tree)
        if branch == base:
            return f"{tree} is on the base branch {base}; ship a feature branch"
        if not title.strip() or not body_file.is_file():
            return "--title must be non-empty and --body-file must name a file"
        where = destination(task, tree, base, repo)
        if isinstance(where, str):
            return where
        refused = refusal(task, tree, phase) if task is not None else ""
        if refused:
            return refused
    except GitError as error:
        return str(error)
    recorded = recorded_steps(task.task, branch) if task is not None else {}
    return Ship(task, tree, branch, where[0], base, repo, where[1], title.strip(), body_file.resolve(),
                attribution.strip() or ATTRIBUTION, phase, recorded)


def ship_task(task_dir: Path | None, title: str, body_file: Path, base: str, repo: str, attribution: str = "",
              phase: bool = False) -> int:
    """Run the steps from the first that is missing or fails its re-check; 0 shipped, 1 stopped, 2 cannot start."""
    ship = prepare(task_dir, title, body_file, base, repo, attribution, phase)
    if isinstance(ship, str):
        print(f"error: {ship}; nothing done", file=sys.stderr)
        return 2
    resumed = False
    for step in STEPS if ship.task is not None and not phase else STEPS[:-1]:
        try:
            if not resumed and step in ship.recorded and STEP_HOLDS[step](ship, ship.recorded[step]):
                print(f"ship: {step} already done")
                continue
            resumed = True
            print(f"ship: {step}")
            value = STEP_RUNS[step](ship)
        except (Stop, GitError, OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"error: ship stopped at {step}: {error}", file=sys.stderr)
            return 1
        if ship.task is not None:
            append_entry(ship.task.task, "SHIP", f"{ship.branch} {step} {value}".strip())
            if step == "pr" and phase and append_pr(ship.task.task, value):
                print(f"recorded PR: {value} (the task stays IMPLEMENTING)")
        ship.recorded[step] = value
    label = name(ship.task) if ship.task is not None else ship.branch
    print(f"shipped: {label} {ship.recorded.get('pr', '')}".rstrip())
    return 0
