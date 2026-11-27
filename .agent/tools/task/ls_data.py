"""What `crew ls` and `crew report` read: rows, the repo and state filters, stale, BLOCKED and `landed`, `--watch`.

`landed`: did a DONE task's change reach the default branch (`yes`, `no`, `unknown`), from the PR
record, not branch ancestry. `landing_bases` (`AGENTS.md`) adds branches where work may land; a match
is `yes` with `backport to <base>`. The watch loop's sleep, clear and cap are parameters.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import task_bootstrap  # noqa: F401

from task_lock import blocked_lines
from task_progress import GITHUB_PR_URL, pr_urls
from task_state import TaskState, head, load, name

from lib.files import FENCE
from lib.gh_reads import add_read_parser, read_argv
from lib.git import GitError, gh, is_ancestor, remote_url, slug_from_url, toplevel

LINE = re.compile(r"^landing_bases:[ \t]*(.*)$", re.M)
BLOCK = re.compile(r"^```landing_bases[ \t]*\n(.*?)^```", re.M | re.S)


def parse(text: str) -> list[str]:
    """The valid patterns `text` declares, in order."""
    raw = [token.strip("`") for found in LINE.findall(FENCE.sub("", text)) for token in found.split()]
    for block in BLOCK.findall(text):
        raw += [line.strip().strip("`") for line in block.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    valid: list[str] = []
    for pattern in raw:
        try:
            re.compile(pattern)
        except re.error:
            continue
        if pattern and pattern not in valid:
            valid.append(pattern)
    return valid


def load_bases(root: Path | None = None) -> list[str]:
    """The patterns in the `AGENTS.md` at the root of the repository around `root` (cwd by default)."""
    try:
        top = toplevel(root)
        return parse((top / "AGENTS.md").read_text(encoding="utf-8", errors="replace"))
    except (GitError, OSError):
        return []


def matches(base: str, patterns: list[str]) -> bool:
    """True when `base` fully matches any pattern."""
    return any(re.fullmatch(pattern, base) for pattern in patterns)


Reader = Callable[[list[str]], "tuple[int, str]"]
Reach = Callable[[str, str], "bool | None"]


def pr_ref(task: Path) -> tuple[str, str, str] | None:
    """`(url, owner/repo, number)` of the newest PR in the task's PR list, or None."""
    urls = pr_urls(task)
    found = GITHUB_PR_URL.match(urls[-1]) if urls else None
    return (found.group(0), found.group(1), found.group(2)) if found else None


def read_pr_actions(arguments: list[str]) -> tuple[int, str]:
    """One `crew-pr-actions.py` read (`view` or `repo` argv), in process; a missing gh or a timeout fails."""
    parser = argparse.ArgumentParser(add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("view", "repo"):
        add_read_parser(commands, command)
    try:
        args = parser.parse_args(arguments)
        done = gh(*read_argv(args.command, args), timeout=45)
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
    return done.returncode, done.stdout


def record_of(arguments: list[str], read: Reader) -> dict | None:
    """The JSON record a read printed, or None when the read failed or printed no object."""
    code, text = read(arguments)
    if code:
        return None
    try:
        record = json.loads(text)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def reachable_from(sha: str, ref: str) -> bool | None:
    """True when the merge commit is already in the local `ref` (`<remote>/<default>`); None otherwise.

    The listing never fetches (a fetch per task made `--all` slow and a watch loop unbearable), so a
    local branch that is behind the server can only prove `yes`, never `no`: not reachable is unknown.
    """
    try:
        return True if is_ancestor(None, sha, ref) else None
    except (GitError, OSError, subprocess.SubprocessError):
        return None


def repo_slug(url: str | None) -> str | None:
    """`owner/repo` (lower case) of a GitHub remote URL, through `lib.git.slug_from_url`."""
    slug = slug_from_url(url)
    return slug.lower() if slug else None


def local_remotes() -> dict[str, str]:
    """`{owner/repo: remote}` for the current directory's `upstream` and `origin` (origin wins a tie)."""
    found: dict[str, str] = {}
    for remote in ("upstream", "origin"):
        try:
            slug = repo_slug(remote_url(None, remote))
        except (GitError, OSError, subprocess.SubprocessError):
            continue
        found.update({slug: remote} if slug else {})
    return found


def memoized(read: Reader) -> Reader:
    """`read` that asks `repo view` once per repository: the default branch is the same for every task."""
    seen: dict[tuple[str, ...], tuple[int, str]] = {}

    def cached(arguments: list[str]) -> tuple[int, str]:
        if arguments[0] != "repo":
            return read(arguments)
        key = tuple(arguments)
        if key not in seen:
            seen[key] = read(arguments)
        return seen[key]
    return cached


def facts(task: Path, read: Reader = read_pr_actions) -> dict | None:
    """The PR record plus the default branch, or None when either cannot be read."""
    ref = pr_ref(task)
    if ref is None:
        return None
    _url, repo, number = ref
    pr = record_of(["view", "--repo", repo, "--pr", number, "--json",
                    "--field", "state,baseRefName,mergeCommit"], read)
    info = record_of(["repo", "--repo", repo, "--json", "--field", "defaultBranchRef"], read)
    default = ((info or {}).get("defaultBranchRef") or {}).get("name")
    if not pr or not default:
        return None
    commit = pr.get("mergeCommit") or {}
    return {"number": number, "state": str(pr.get("state") or "").upper(),
            "base": pr.get("baseRefName") or "", "default": default,
            "merge_commit": commit.get("oid") if isinstance(commit, dict) else None}


def is_normal_base(found: dict, patterns: list[str]) -> bool:
    """The default branch, or a base the repo's `landing_bases` names."""
    return found["base"] == found["default"] or matches(found["base"], patterns)


def verdict(found: dict | None, reach: Reach = reachable_from, patterns: list[str] | None = None,
            remote: str | None = "origin") -> str:
    """`yes`, `no`, or `unknown` for one task's PR facts; `remote` is None for a PR of another repository."""
    if found is None:
        return "unknown"
    if found["state"] != "MERGED":
        return "no"
    if is_normal_base(found, patterns or []):
        return "yes"
    if remote is None:
        return "unknown"
    if not found["merge_commit"]:
        return "no"
    reached = reach(found["merge_commit"], f"{remote}/{found['default']}")
    return "unknown" if reached is None else ("yes" if reached else "no")


def flag(found: dict | None, patterns: list[str] | None = None) -> str:
    """A note for an open or merged PR whose base is not a normal one, else an empty string."""
    if found is None or found["state"] not in ("OPEN", "MERGED") or is_normal_base(found, patterns or []):
        return ""
    return f"PR #{found['number']} {found['state'].lower()} into {found['base']}, not {found['default']}"


Local = Callable[[], "dict[str, str]"]


def landed_row(task: Path, read: Reader = read_pr_actions, reach: Reach = reachable_from,
               patterns: list[str] | None = None, local: Local = local_remotes) -> dict:
    """`{landed, flag}` for one DONE task, plus `note: backport to <base>` for a merge into a landing base.

    `patterns` are the repo's `landing_bases`; None reads them from the AGENTS.md of the current repository.
    They and reachability belong to this checkout, so a PR of a repository that is neither `origin` nor
    `upstream` is `unknown` when its base is not the default branch, and gets no backport note.
    """
    ref = pr_ref(task)
    remote = (local() or {}).get(ref[1].lower()) if ref is not None else None
    found = facts(task, read)
    bases = (load_bases() if patterns is None else patterns) if remote else []
    row = {"landed": verdict(found, reach, bases, remote), "flag": flag(found, bases)}
    if found and found["state"] == "MERGED" and found["base"] != found["default"] and matches(found["base"], bases):
        row["note"] = f"backport to {found['base']}"
    return row


def landed_rows(tasks: list[Path], read: Reader = read_pr_actions, reach: Reach = reachable_from,
                patterns: list[str] | None = None, local: Local = local_remotes) -> list[dict]:
    """`landed_row` for each task, asking `repo view` once per repository and reading the remotes once."""
    cached, here = memoized(read), local()
    bases = load_bases() if patterns is None else patterns
    return [landed_row(task, cached, reach, bases, lambda: here) for task in tasks]


def landed_lines(rows: list[tuple[str, Path]], read: Reader = read_pr_actions,
                 reach: Reach = reachable_from, patterns: list[str] | None = None,
                 local: Local = local_remotes) -> list[str]:
    """One `landed:` line per DONE task, with the backport note or the non-default base flag."""
    lines = []
    for (slug, _task), row in zip(rows, landed_rows([task for _, task in rows], read, reach, patterns, local)):
        note = f" ({row['note']})" if "note" in row else (f"  ({row['flag']})" if row["flag"] else "")
        lines.append(f"  {slug}  landed: {row['landed']}{note}")
    return lines


DEFAULT_INTERVAL = 3.0
CLEAR = "\033[2J\033[H"
LandedReader = Callable[["list[tuple[str, Path]]"], "list[str]"]


@dataclass
class Snapshot:
    """The listing's data at one moment: rows, BLOCKED lines, and `landed` lines for DONE tasks."""

    rows: list[TaskState] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    landed: list[str] = field(default_factory=list)


def load_rows(tasks_dir: Path) -> list[TaskState]:
    """Every task directory that has a SPEC.md; a malformed one is skipped with a warning."""
    rows = []
    for task in sorted(tasks_dir.glob("*")):
        if not (task / "SPEC.md").exists():
            continue
        try:
            rows.append(load(task))
        except (OSError, ValueError, AttributeError) as error:
            print(f"warning: skipping {task.name}: {error}", file=sys.stderr)
    return rows


STALE_DAYS = 14


def repo_filter(given: str | None, here: Local = local_remotes) -> set[str] | None:
    """The `owner/repo` names `--repo` keeps (lower case), or None for every repository.

    No flag means the repository around the cwd (its `origin` and `upstream`), or every repository
    outside one; `all` means every repository; a bare name matches any owner.
    """
    if given is None:
        return set(here()) or None
    return None if given.lower() == "all" else {given.lower()}


def select(rows: list[TaskState], repos: set[str] | None, states: list[str] | None = None) -> list[TaskState]:
    """The rows in `repos` (a task with no recorded repository is in every one) and in `states`."""
    def in_repo(r: TaskState) -> bool:
        return repos is None or not r.repo or r.repo.lower() in repos or r.repo.lower().split("/")[-1] in repos

    wanted = {state.upper() for state in states or []}
    return [r for r in rows if in_repo(r) and (not wanted or head(r) in wanted)]


def stale(r: TaskState) -> bool:
    """IMPLEMENTING with no PROGRESS activity for `STALE_DAYS`: `crew ls` folds these into one line."""
    return head(r) == "IMPLEMENTING" and r.activity >= STALE_DAYS


def shown_done(rows: list[TaskState], limit: int | None) -> list[TaskState]:
    """The DONE rows the table will show: open rows come first and count against `--limit`, done ones by age."""
    done = sorted((r for r in rows if head(r) == "DONE"), key=lambda r: r.age)
    return done if limit is None else done[:max(0, limit - sum(1 for r in rows if head(r) != "DONE"))]


def snapshot(rows: list[TaskState], show_done: bool, landed: LandedReader = landed_lines,
             limit: int | None = None) -> Snapshot:
    """The BLOCKED and `landed` lines for already-loaded rows; `landed` reads GitHub, so only when asked.

    `limit` (`--limit`) is applied first: only the DONE rows the table shows are read.
    """
    done = [(name(r), r.task) for r in shown_done(rows, limit)]
    return Snapshot(rows=rows, blocked=blocked_lines([(name(r), r.task) for r in rows if head(r) != "DONE"]),
                    landed=landed(done) if show_done and done else [])


def gather(tasks_dir: Path, show_done: bool = False, landed: LandedReader = landed_lines,
           limit: int | None = None) -> Snapshot:
    """Load the rows under `tasks_dir` and everything the listing derives from them."""
    return snapshot(load_rows(tasks_dir), show_done, landed, limit)


class LandedCache:
    """`landed` lines kept per task for `ttl` seconds, so a `--watch --all` loop reads GitHub once a minute."""

    def __init__(self, ttl: float = 60.0, clock: Callable[[], float] = time.monotonic,
                 landed: LandedReader = landed_lines) -> None:
        self.ttl, self.clock, self.landed = ttl, clock, landed
        self.kept: dict[str, tuple[float, str]] = {}

    def lines(self, rows: list[tuple[str, Path]]) -> list[str]:
        now = self.clock()
        stale = [(n, t) for n, t in rows if str(t) not in self.kept or now - self.kept[str(t)][0] >= self.ttl]
        for (_, t), line in zip(stale, self.landed(stale) if stale else []):
            self.kept[str(t)] = (now, line)
        return [self.kept[str(t)][1] for _, t in rows if str(t) in self.kept]


def clear_screen() -> None:
    sys.stdout.write(CLEAR)
    sys.stdout.flush()


def watch(render: Callable[[], None], interval: float = DEFAULT_INTERVAL, sleep: Callable[[float], None] = time.sleep,
          clear: Callable[[], None] = clear_screen, max_iterations: int | None = None) -> int:
    """Render into a buffer, then clear and print it, every `interval` seconds; Ctrl-C ends it with 0.

    The screen is cleared only when the next frame is ready, so a slow read never leaves it blank.
    `max_iterations` caps the draws.
    """
    drawn = 0
    try:
        while max_iterations is None or drawn < max_iterations:
            frame = io.StringIO()
            with contextlib.redirect_stdout(frame):
                render()
            clear()
            sys.stdout.write(frame.getvalue())
            sys.stdout.flush()
            drawn += 1
            if max_iterations is not None and drawn >= max_iterations:
                break
            sleep(interval)
    except KeyboardInterrupt:
        return 0
    return 0
