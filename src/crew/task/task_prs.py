"""The PRs reconcile finds for IMPLEMENTING tasks: `gh pr list --head <branch>`, read-only, cached and bounded.

A task is asked at most once per `TTL` seconds, never once it has a PR; a repository's default branch (never
asked) and parent, from one `gh repo view`, are kept as long. A fork's task with no PR in the fork is asked in
the parent, keeping the fork owner's heads. The cache is `.pr-lookup.json` beside the tasks directory. Lookups
run on `WORKERS` threads; with a `budget` every call ends at one deadline, and a task not answered stays unchecked.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from crew.lib.files import atomic_write
from crew.lib.git import gh
from crew.task.task_progress import GITHUB_PR_URL
from crew.task.task_state import TaskState, head

CACHE_NAME = ".pr-lookup.json"
TTL = 86400
WORKERS = 8
CALL_TIMEOUT = 20.0
POLL = 0.05  # seconds between deadline checks while lookups run
Reader = Callable[[list[str], float], "tuple[int, str]"]


@dataclass
class Lookup:
    """What one search found: `{task dir: PR URLs}`, and how many due tasks it did not get an answer for."""

    found: dict[Path, list[str]] = field(default_factory=dict)
    unchecked: int = 0


def gh_read(arguments: list[str], timeout: float) -> tuple[int, str]:
    """One read-only `gh` call as `(exit code, stdout)`; a missing gh or a timeout is exit 1."""
    try:
        done = gh(*arguments, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, done.stdout


def parsed(read: Reader, arguments: list[str], timeout: float) -> object:
    """The JSON a read printed, or None when it failed or printed none."""
    code, text = read(arguments, timeout)
    try:
        return json.loads(text) if code == 0 else None
    except ValueError:
        return None


def repo_facts(read: Reader, repo: str, timeout: float) -> tuple[str, str] | None:
    """`(default branch, parent owner/name or "")` from one `gh repo view`; None when the read failed."""
    info = parsed(read, ["repo", "view", repo, "--json", "defaultBranchRef,parent"], timeout)
    if not isinstance(info, dict):
        return None
    parent = info.get("parent") if isinstance(info.get("parent"), dict) else {}
    owner, name = (parent.get("owner") or {}).get("login") or "", parent.get("name") or ""
    return (info.get("defaultBranchRef") or {}).get("name") or "", f"{owner}/{name}" if owner and name else ""


def branch_urls(read: Reader, repo: str, branch: str, owner: str | None, timeout: float, state: str = "all") -> list[str] | None:
    """The PR URLs of `branch` in `repo` in `state` (gh's `--state`), only those whose head is `owner`'s when given;
    None when the read failed."""
    fields = "url,headRepositoryOwner" if owner else "url"
    listed = parsed(read, ["pr", "list", "--head", branch, "--repo", repo, "--state", state, "--json", fields], timeout)
    if not isinstance(listed, list):
        return None

    def head_owner(item: dict) -> str:
        return str((item.get("headRepositoryOwner") or {}).get("login", "")).lower()

    items = [item for item in listed if isinstance(item, dict) and (not owner or head_owner(item) == owner.lower())]
    return [url for url in (str(item.get("url")) for item in items) if GITHUB_PR_URL.fullmatch(url)]


def load_cache(path: Path) -> dict:
    """`{"tasks": {uuid: checked_at}, "repos": {owner/repo: [checked_at, default branch, parent or ""]}}`; empty
    when unreadable. A repository entry of another shape is asked again."""
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    cache = cache if isinstance(cache, dict) else {}
    return {key: cache[key] if isinstance(cache.get(key), dict) else {} for key in ("tasks", "repos")}


def due(rows: list[TaskState], cache: dict, now: float) -> list[TaskState]:
    """The IMPLEMENTING tasks with a repository and a branch, no PR recorded, not asked within `TTL`."""

    def stamp(r: TaskState) -> float:
        value = cache["tasks"].get(r.uuid)
        return value if isinstance(value, (int, float)) else 0.0

    return [
        r
        for r in rows
        if head(r) == "IMPLEMENTING" and r.repo and isinstance(r.meta.get("branch"), str) and r.meta["branch"] and not r.prs and now - stamp(r) >= TTL
    ]


def branch_prs(
    rows: list[TaskState],
    cache_path: Path | None,
    budget: float | None = None,
    write: bool = False,
    read: Reader = gh_read,
    now: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Lookup:
    """Ask GitHub for the PRs of each due task's branch; with `write`, record every answer in the cache.

    `budget` (seconds) bounds the whole search; None waits for every call. A failed read (offline, gh
    missing or signed out) leaves its task unchecked, so the next run asks again.
    """
    moment = time.time() if now is None else now
    cache = load_cache(cache_path) if cache_path else {"tasks": {}, "repos": {}}
    wanted = due(rows, cache, moment)
    if not wanted:
        return Lookup()
    deadline = None if budget is None else clock() + budget

    def timeout() -> float:
        return CALL_TIMEOUT if deadline is None else max(0.05, min(CALL_TIMEOUT, deadline - clock()))

    pool = ThreadPoolExecutor(max_workers=WORKERS)
    facts: dict[str, Future] = {}
    asked: list[str] = []
    for repo in sorted({r.repo for r in wanted}):  # queued first, so a task job never waits behind its own repo
        hit = cache["repos"].get(repo)
        if isinstance(hit, list) and len(hit) == 3 and isinstance(hit[0], (int, float)) and moment - hit[0] < TTL:
            facts[repo] = Future()
            facts[repo].set_result((str(hit[1]), str(hit[2])))
        else:
            facts[repo] = pool.submit(lambda name: repo_facts(read, name, timeout()), repo)  # timeout() at run time
            asked.append(repo)

    def lookup(r: TaskState) -> list[str] | None:
        known, branch = facts[r.repo].result(), r.meta["branch"]
        if known is None or branch == known[0]:
            return None if known is None else []
        urls = branch_urls(read, r.repo, branch, None, timeout())
        if urls or urls is None or not known[1]:
            return urls
        return branch_urls(read, known[1], branch, r.repo.split("/")[0], timeout())  # a fork: its PR is upstream

    jobs = {pool.submit(lookup, r): r for r in wanted}
    pending = set(jobs)
    while pending and (deadline is None or clock() < deadline):  # `clock` decides the deadline, polled
        _, pending = wait(pending, timeout=None if deadline is None else POLL, return_when=FIRST_COMPLETED)
    pool.shutdown(wait=False, cancel_futures=True)  # running calls end at the deadline through their timeout
    result = collect({job: r for job, r in jobs.items() if job not in pending}, cache, moment)
    result.unchecked += len(pending)
    for repo in asked:
        job = facts[repo]
        if job.done() and not job.cancelled() and job.exception() is None and job.result() is not None:
            cache["repos"][repo] = [moment, *job.result()]
    if write and cache_path:
        save_cache(cache_path, cache, {r.uuid for r in rows})
    return result


def collect(finished: dict[Future, TaskState], cache: dict, moment: float) -> Lookup:
    """The answers of the finished lookups, each stamped in `cache`; a crash is one warning and stays unchecked."""
    result = Lookup()
    for job, r in finished.items():
        error = job.exception()
        if error is not None:
            print(f"warning: PR lookup for {r.slug}: {type(error).__name__}: {error}", file=sys.stderr)
        urls = job.result() if error is None else None
        if urls is None:
            result.unchecked += 1
            continue
        cache["tasks"][r.uuid] = moment
        result.found.update({r.task: urls} if urls else {})
    return result


def save_cache(path: Path, cache: dict, live: set[str]) -> None:
    """Write the cache, keeping only the tasks that still exist."""
    cache["tasks"] = {uuid: at for uuid, at in cache["tasks"].items() if uuid in live}
    try:
        atomic_write(path, json.dumps(cache, indent=1, sort_keys=True) + "\n")
    except OSError as error:
        print(f"warning: PR lookup cache not written: {error}", file=sys.stderr)
