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
from datetime import UTC, datetime
from pathlib import Path

from crew.core.task.task_progress import PROGRESS_FILE, Entry, append_transition, issue_url, latest, pr_urls, read_entries
from crew.core.task.task_record import GATE_STAMP, recorded_status
from crew.core.task.task_status import STATUS, StatusError, canonical, read_status, review_file, reviewed_at, spec_field, verdict_word
from crew.core.task.task_status import head as state_head
from crew.lib.files import atomic_write
from crew.lib.git import GitError, is_ancestor, slug_from_url
from crew.lib.markdown import FENCED

BORN = "DRAFTING"  # the recorded status of a spec no transition has moved


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
    recorded: str = ""  # the status crew-task last recorded in PROGRESS.md (`recorded_status`), "" for none
    legacy: bool = True  # no gate-stamped transition yet (`recorded_status`)

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
            "task": self.task,
            "text": self.text,
            "meta": self.meta,
            "status": self.status,
            "verdict": self.verdict,
            "age": self.age,
            "open": self.open,
            "done": self.done,
        }


def head(r: TaskState) -> str:
    """The normalized state token of a loaded task record (the contract's `head` over its status)."""
    return state_head(r.status)


def recorded_state(r: TaskState) -> str:
    """The status the spec must have: the recorded one, DRAFTING for a task no transition moved."""
    return r.recorded or BORN


def closed_outside(r: TaskState) -> bool:
    """A legacy task (no gate stamp) whose DONE spec is recorded IMPLEMENTING or nothing: closed by hand before the
    gates stamped their transitions. Not TAMPERED; a stamped task must reach DONE through `mark-done`."""
    return r.legacy and head(r) == "DONE" and r.recorded in ("IMPLEMENTING", "")


def tampered(r: TaskState) -> str:
    """`TAMPERED (spec says X, crew-task recorded Y)` when the spec's Status is not the recorded one, else "". Not
    tampered: a spec with no Status yet and no transition (a draft being written, as the Status guard lets a spec be
    born), and `closed_outside`; a DONE spec recorded DRAFTING, APPROVED or ON-HOLD skipped implementation and is."""
    spec, want = head(r), recorded_state(r)
    if spec == want or (not spec and want == BORN) or closed_outside(r):
        return ""
    return f"TAMPERED (spec says {spec or 'unset'}, crew-task recorded {want})"


def tamper_refusal(r: TaskState) -> str:
    """The words every gate refuses a tampered task with, or ""."""
    found = tampered(r)
    return (
        (
            f"error: {name(r)}: {found}; nothing written (crew-task.py restore-status {r.task} writes the recorded status back; --accept <note> records the spec's)"
        )
        if found
        else ""
    )


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
        [] if review_not_behind(r) else ["the review does not cover the branch tip; re-run crew review"]
    )


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
# An unresolved clarification blocks implementation; one shown inside a fenced example does not.
UNRESOLVED = re.compile(r"\[NEEDS CLARIFICATION", re.M)

ACTIVITY_FILES = ("SPEC.md", PROGRESS_FILE, "REVIEW.md", "REPORT.md")


def unresolved(spec_text: str) -> bool:
    return bool(UNRESOLVED.search(FENCED.sub("", spec_text)))


def spec_branch(spec_text: str) -> str:
    return spec_field(spec_text, "Branch")


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


def last_activity(task: Path, entries: list[Entry] | None = None) -> float:
    """When the task last moved, as a POSIX time: its newest PROGRESS entry, else `newest_mtime`."""
    stamped = latest(task, entries)
    return stamped.timestamp() if stamped else newest_mtime(task)


def days_since(moment: float) -> int:
    return int((datetime.now(UTC).timestamp() - moment) / 86400)


def load(task: Path) -> TaskState:
    """The record every consumer reads: identity, status, verdict, age, activity, checkbox counts, and the status
    PROGRESS.md records (read once for the PR list, the activity and `recorded`)."""
    spec = task / "SPEC.md"
    text = spec.read_text(encoding="utf-8")
    metadata = task / ".task-id"
    meta = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {}
    if not isinstance(meta, dict):
        meta = {}
    status = STATUS.search(text)
    review = review_file(task)
    verdict = verdict_word(review.read_text(encoding="utf-8")) if review else None
    entries = read_entries(task)
    record = TaskState(
        task=task,
        text=text,
        meta=meta,
        status=status.group(2).strip() if status else None,
        verdict=verdict or "?",
        age=days_since(newest_mtime(task)),
        open=len(OPEN_ITEM.findall(text)),
        done=len(DONE_ITEM.findall(text)),
        activity=days_since(last_activity(task, entries)),
        prs=pr_urls(task, entries),
    )
    record.recorded, record.legacy = recorded_status(entries)
    # A `.task-id` with a missing or empty PROGRESS.md is strict: deleting the record never makes a task lenient.
    record.legacy = record.legacy and not (metadata.exists() and not entries)
    record.issue = issue_url(text, record.repo)
    return record


def decide(r: TaskState, rules: dict) -> dict | None:
    """The first transition rule that matches this spec, or None."""
    for rule in rules["auto"]:
        if head(r) in rule["from"] and all(PREDICATES[p](r, rules) for p in rule["when"]):
            return rule
    return None


def set_status(r: TaskState, value: str, transition: str) -> bool:
    """Write the new `## Status` value and record `transition`, refusing a tampered task (`tampered`) and a spec that
    changed since it was read."""
    refusal = tamper_refusal(r)
    if refusal:
        print(refusal, file=sys.stderr)
        return False
    return write_status(r, value, transition)


def record_transition(r: TaskState, transition: str) -> None:
    """Append `transition` with the gate stamp, the only way a status reaches PROGRESS.md; raises `OSError`."""
    append_transition(r.task, f"{transition} {GATE_STAMP}")


def write_status(r: TaskState, value: str, transition: str) -> bool:
    """The write of `set_status` with no tamper check: `restore-status` uses it to put the recorded value back.

    The stamped transition is appended first: a failed append writes nothing, so a real move never reads as TAMPERED.
    A spec write that fails after it is undone by a compensating stamped transition back to the spec's status.
    """
    spec = r.task / "SPEC.md"
    try:
        current = spec.read_text(encoding="utf-8")
        if current != r.text:
            raise OSError("SPEC.md changed since it was read")
        updated, count = STATUS.subn(lambda m: m.group(1) + value, current, count=1)
        if count != 1:
            raise OSError("no Status value found")
        record_transition(r, transition)
    except OSError as error:
        print(f"error: {name(r)}: {error}; nothing written", file=sys.stderr)
        return False
    try:
        atomic_write(spec, updated)
    except OSError as error:
        print(f"error: {name(r)}: SPEC.md not written: {error}", file=sys.stderr)
        try:
            record_transition(r, f"{state_head(value)} → {head(r) or BORN} (reverted: SPEC.md not written)")
        except OSError as again:
            print(f"error: {name(r)}: PROGRESS.md not reverted: {again}", file=sys.stderr)
        return False
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
        print(f"{'normalized' if apply else 'would normalize'}: {spec}: {before} -> {canonical(before)}", file=sink)
    verb = "normalized" if apply else "would normalize"
    print(f"{verb} {changed} of {len(specs)} spec(s)" + ("" if changed else ": already canonical"), file=sink)
    if failed:
        print(f"error: {failed} spec(s) not written", file=sys.stderr)
        return -1
    return changed
