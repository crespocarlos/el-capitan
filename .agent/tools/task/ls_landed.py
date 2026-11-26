"""Did a DONE task's change reach the default branch? `yes`, `no`, or `unknown`.

`DONE` only means a draft PR was opened. Stacked PRs once merged into their parent branches, so the
work looked merged and never landed. The answer comes from the PR record, read through
`crew-pr-actions.py` (read-only `gh`), not from branch ancestry: a squash or rebase merge leaves the
branch outside the default branch's history, and a removed worktree leaves nothing to ask.

    yes      merged with base equal to the default branch, or the merge commit is reachable from
             the local `<remote>/<default>` (a stack merged on afterwards; the listing never fetches)
    no       merged into another base the local branch can rule on, or the PR is still open or was closed
    unknown  no PR url was recorded, the PR record or the network is unavailable, the PR belongs to
             a repository that is neither `origin` nor `upstream` here, or reachability cannot be shown.

`<remote>` is whichever of `origin` and `upstream` the PR's repository is (the fork workflow: origin
is the fork, the PR targets upstream). `flag` names any open or merged PR whose base is not the
default branch. A repo that lists `landing_bases` in its AGENTS.md (`ls_bases.py`) treats a matching
base as normal: a merged PR into it is `yes` with the note `backport to <base>`, never flagged.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from lib.git import GitError, is_ancestor, remote_url  # noqa: E402
from ls_bases import load as load_bases, matches  # noqa: E402

PR_ACTIONS = _TOOLS / "review" / "crew-pr-actions.py"
PR_URL = re.compile(r"PR opened: (https?://[^/\s]+/([^/\s]+/[^/\s]+)/pull/(\d+))")
Reader = Callable[[list[str]], "tuple[int, str]"]
Reach = Callable[[str, str], "bool | None"]


def pr_ref(task: Path) -> tuple[str, str, str] | None:
    """`(url, owner/repo, number)` from the last `PR opened:` line of PROGRESS.md, or None."""
    try:
        found = PR_URL.findall((task / "PROGRESS.md").read_text(encoding="utf-8"))
    except OSError:
        return None
    return found[-1] if found else None


def read_pr_actions(arguments: list[str]) -> tuple[int, str]:
    """Run one read of `crew-pr-actions.py`; a missing gh or a timeout is a failed read."""
    try:
        done = subprocess.run([sys.executable, str(PR_ACTIONS), *arguments], capture_output=True,
                              text=True, timeout=45)
    except (OSError, subprocess.SubprocessError):
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
    """`owner/repo` (lower case) of a GitHub remote URL in https, ssh or scp form, or None."""
    found = re.search(r"[:/]([^/:\s]+)/([^/\s]+?)(?:\.git)?/?$", (url or "").strip())
    return f"{found.group(1)}/{found.group(2)}".lower() if found else None


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
    for (name, _task), row in zip(rows, landed_rows([task for _, task in rows], read, reach, patterns, local)):
        note = f" ({row['note']})" if "note" in row else (f"  ({row['flag']})" if row["flag"] else "")
        lines.append(f"  {name}  landed: {row['landed']}{note}")
    return lines
