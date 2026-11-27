"""Task state: the SPEC record, the status write, the reconcile rule matching and the status migration.

`task_report.py` renders this record, `task_gates.py` applies the transitions, `task_resolve.py`
finds it; the `## Status` contract is `task_status.py`. `normalize-status` rewrites only a legacy
token (`done` to `DONE`), keeps any suffix and reports each file; a second run finds nothing.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_progress import PROGRESS_FILE, append_transition, latest, pr_urls
from task_status import STATUS, StatusError, canonical, read_status, review_file, reviewed_at
from task_status import head as state_head

from lib.files import atomic_write
from lib.git import GitError, is_ancestor, slug_from_url


@dataclass
class TaskState:
    """One spec's state as every consumer reads it: identity, status, verdict, age, counts.

    Built once by `load` from SPEC.md and `.task-id`, then handed to the renderer and the gates
    rather than re-derived from string keys at each call site. `task` and `text` stay because the
    write path compares the text it read against the file on disk before replacing the status.
    """

    task: Path
    text: str
    meta: dict
    status: str | None
    verdict: str
    age: int
    open: int
    done: int
    activity: int = 0  # days since `last_activity`: the AGE `crew ls` shows
    issue: str = ""  # the GitHub issue URL the spec names (`issue_url`), or ""
    prs: list[str] = field(default_factory=list)  # the PR list, oldest first (`task_progress.pr_urls`)

    @property
    def uuid(self) -> str:
        """The task directory name, which is the task's uuid in `~/.agent/tasks`."""
        return self.task.name

    @property
    def slug(self) -> str:
        """The recorded slug, falling back to the directory name when `.task-id` carries none."""
        return self.meta.get("slug", self.task.name)

    @property
    def branch(self) -> str:
        """The recorded branch for display, or `-` when absent. An explicit null is preserved."""
        return self.meta.get("branch", "-")

    def branch_name(self, default: str) -> str:
        """The recorded branch, falling back to `default` when `.task-id` did not record one."""
        return self.meta.get("branch", default)

    @property
    def repo(self) -> str:
        """`owner/repo` of the recorded remote, or "" when `.task-id` records none."""
        url = self.meta.get("repo_remote_url")
        return (slug_from_url(url) or "") if isinstance(url, str) else ""

    def to_json(self) -> dict:
        """The record as JSON, in the key order the loader has always produced."""
        return {
            "task": self.task, "text": self.text, "meta": self.meta, "status": self.status,
            "verdict": self.verdict, "age": self.age, "open": self.open, "done": self.done,
        }


def head(r: TaskState) -> str:
    """The normalized state token of a loaded task record (the contract's `head` over its status)."""
    return state_head(r.status)


def review_not_behind(r: TaskState) -> bool:
    """False only when git proves the review's `Reviewed at:` commit is not an ancestor of the task's branch tip.

    The tip is the task's recorded branch, not the cwd's HEAD: reconcile runs from whatever checkout the
    session opened, usually the default branch, while the work sits in a worktree sharing its objects.
    No review, no commit, no branch, or a commit or branch git cannot resolve passes; `mark-done`
    repeats the check against HEAD in the implementation checkout and refuses what it cannot verify.
    """
    commit, branch = reviewed_at(review_file(r.task)), r.meta.get("branch")
    if not commit or not isinstance(branch, str) or not branch:
        return True
    try:
        return is_ancestor(None, commit, branch)
    except GitError:
        return True


def done_blockers(r: TaskState) -> list[str]:
    """Why a task with a PR is not ready to mark done, in the words reconcile prints."""
    return ([f"{r.open} unchecked" if r.open else "no checked criteria"] if r.open or not r.done else []) + (
        [] if review_not_behind(r) else ["the review does not cover the branch tip; re-run crew review"])


PREDICATES = {
    "all_checked": lambda r, rules: r.open == 0,
    "has_checkboxes": lambda r, rules: r.done > 0,
    "verdict_ok": lambda r, rules: r.verdict.lower() in ("pass", "warn"),
    "has_pr": lambda r, rules: bool(r.prs),
    "no_pr": lambda r, rules: not r.prs,
    "review_not_behind": lambda r, rules: review_not_behind(r),
    "idle": lambda r, rules: r.age > rules["idle_days"],
}
KINDS = ("done", "pr-open", "ready", "stalled", "hold")
SAMPLE_FIELDS = dict(idle_days=0, prior="X", from_state="X")
OPEN_ITEM = re.compile(r"^\s*[-*]\s\[ \]", re.M)
DONE_ITEM = re.compile(r"^\s*[-*]\s\[[xX]\]", re.M)
# A verdict is a bare word ending its clause; pass-with-nits or "pass | warn" do not count.
VERDICT = re.compile(
    r"^\s*(?:#+\s*)?(?:\*\*)?Verdict:?(?:\*\*)?\s*([A-Za-z]+)(?=[ \t]*(?:[.:;,]|$))", re.M
)
# An unresolved clarification blocks implementation; one shown inside a fenced example does not.
UNRESOLVED = re.compile(r"\[NEEDS CLARIFICATION", re.M)
FENCED = re.compile(r"^```.*?^```", re.M | re.S)
ACTIVITY_FILES = ("SPEC.md", PROGRESS_FILE, "REVIEW.md", "REPORT.md")


def unresolved(spec_text: str) -> bool:
    return bool(UNRESOLVED.search(FENCED.sub("", spec_text)))


ISSUE_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)")  # no `[` or `]`: a TUI link carries it
ISSUE_LINE = re.compile(r"^[#>*\s-]*Issue\**:\**[ \t]*(.*)$", re.M)
ISSUE_REF = re.compile(r"(?<![\w/])(?:([\w.-]+/[\w.-]+))?#(\d+)\b")


def issue_url(spec_text: str, repo: str) -> str:
    """The GitHub issue a spec names: its `Issue:` line (a URL, `#n` or `owner/repo#n`), else the first issue URL.

    `crew spec` writes the line; older specs name the issue anywhere in their prose. Fenced text is an
    example, never the task's issue, and `#n` needs the task's `repo` (`owner/repo`).
    """
    text = FENCED.sub("", spec_text)
    for line in ISSUE_LINE.findall(text):
        found = ISSUE_URL.search(line)
        if found:
            return found.group(0)
        ref = ISSUE_REF.search(line)
        if ref and (ref.group(1) or repo):
            return f"https://github.com/{ref.group(1) or repo}/issues/{ref.group(2)}"
    found = ISSUE_URL.search(text)
    return found.group(0) if found else ""


class RulesError(ValueError):
    """A malformed `transitions.json`: the entry point reports it and exits 2."""


def load_rules() -> dict:
    """The transitions file, validated so a malformed rule aborts instead of silently matching."""
    path = Path(__file__).resolve().parent / "transitions.json"
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rules["idle_days"], int):
            raise ValueError("idle_days must be an integer")
        for i, rule in enumerate(rules["auto"]):
            where = f"auto[{i}]"
            for key in ("from", "when", "kind"):
                if key not in rule:
                    raise ValueError(f'{where}: missing "{key}"')
            if rule["kind"] not in KINDS:
                raise ValueError(f"{where}: kind must be one of {KINDS}")
            unknown = [p for p in rule["when"] if p not in PREDICATES]
            if unknown:
                raise ValueError(f"{where}: unknown predicate {unknown}")
            if rule["kind"] == "hold":
                for key in ("status", "log"):
                    if key not in rule:
                        raise ValueError(f'{where}: hold rule needs "{key}"')
                    rule[key].format(**SAMPLE_FIELDS)
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise RulesError(f"error: {path.name}: {type(error).__name__}: {error}") from error
    return rules


def name(r: TaskState) -> str:
    return r.slug


def newest_mtime(task: Path) -> float:
    """The newest modification time of the task's activity files (0 when it has none)."""
    return max([(task / f).stat().st_mtime for f in ACTIVITY_FILES if (task / f).exists()] or [0.0])


def last_activity(task: Path) -> float:
    """When the task last moved, as a POSIX time: its newest PROGRESS entry, else `newest_mtime`."""
    stamped = latest(task)
    return stamped.timestamp() if stamped else newest_mtime(task)


def days_since(moment: float) -> int:
    return int((datetime.now(timezone.utc).timestamp() - moment) / 86400)


def load(task: Path) -> TaskState:
    """The record every consumer reads: identity, status, verdict, age, activity, and checkbox counts."""
    spec = task / "SPEC.md"
    text = spec.read_text(encoding="utf-8")
    metadata = task / ".task-id"
    meta = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {}
    if not isinstance(meta, dict):
        meta = {}
    status = STATUS.search(text)
    review = review_file(task)
    verdicts = VERDICT.findall(review.read_text(encoding="utf-8")) if review else []
    record = TaskState(
        task=task, text=text, meta=meta, status=status.group(2).strip() if status else None,
        verdict=verdicts[-1] if verdicts else "?", age=days_since(newest_mtime(task)),
        open=len(OPEN_ITEM.findall(text)), done=len(DONE_ITEM.findall(text)),
        activity=days_since(last_activity(task)), prs=pr_urls(task),
    )
    record.issue = issue_url(text, record.repo)
    return record


def decide(r: TaskState, rules: dict) -> dict | None:
    """The first transition rule that matches this spec, or None."""
    for rule in rules["auto"]:
        if head(r) in rule["from"] and all(PREDICATES[p](r, rules) for p in rule["when"]):
            return rule
    return None


def set_status(r: TaskState, value: str, transition: str) -> bool:
    """Write the new `## Status` value, refusing when the spec changed since it was read."""
    spec = r.task / "SPEC.md"
    try:
        current = spec.read_text(encoding="utf-8")
        if current != r.text:
            raise OSError("SPEC.md changed since it was read")
        updated, count = STATUS.subn(lambda m: m.group(1) + value, current, count=1)
        if count != 1:
            raise OSError("no Status value found")
        atomic_write(spec, updated)
    except OSError as error:
        print(f"error: {name(r)}: {error}", file=sys.stderr)
        return False
    try:
        append_transition(r.task, transition)
    except OSError as error:
        print(f"warning: {name(r)}: PROGRESS.md not updated: {error}", file=sys.stderr)
    print(f"applied: {name(r)} -> {value.split()[0]}")
    return True


def rewritten(path: Path) -> str:
    """The SPEC.md text with a canonical status, or "" when the file needs no change.

    Returns "" for an unreadable file, an unset status, an already-canonical value, and an unknown
    token: a migration reports what it cannot fix rather than guessing a state for it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = STATUS.search(text)
    if not match:
        return ""
    value = match.group(2).strip()
    try:
        if canonical(value) == value:
            return ""
    except StatusError:
        return ""
    return STATUS.sub(lambda m: m.group(1) + canonical(m.group(2).strip()), text, count=1)


def unknown_status(path: Path) -> str:
    """The status value of a spec that cannot be normalized because its token is not in the set."""
    value = read_status(path)
    if not value:
        return ""
    try:
        canonical(value)
    except StatusError as error:
        return str(error)
    return ""


def normalize_all(tasks_dir: Path, apply: bool, out=None) -> int:
    """Report, and with `apply` rewrite, every spec whose status is not canonical.

    The return value counts the files changed (or, in a dry run, would change), so a caller can
    assert idempotence: the second run returns 0 and prints the same "already canonical" summary.
    """
    sink = out or sys.stdout
    changed = 0
    failed = 0
    specs = sorted(tasks_dir.glob("*/SPEC.md"))
    for spec in specs:
        problem = unknown_status(spec)
        if problem:
            print(f"skip: {spec.parent.name}: {problem}", file=sys.stderr)
            continue
        updated = rewritten(spec)
        if not updated:
            continue
        before = read_status(spec) or ""
        if apply:
            try:
                atomic_write(spec, updated)
            except OSError as error:
                failed += 1
                print(f"error: {spec}: {error}", file=sys.stderr)
                continue
        changed += 1
        print(f"{'normalized' if apply else 'would normalize'}: {spec}: "
              f"{before} -> {canonical(before)}", file=sink)
    verb = "normalized" if apply else "would normalize"
    print(f"{verb} {changed} of {len(specs)} spec(s)" + ("" if changed else ": already canonical"),
          file=sink)
    if failed:
        print(f"error: {failed} spec(s) not written", file=sys.stderr)
        return -1
    return changed
