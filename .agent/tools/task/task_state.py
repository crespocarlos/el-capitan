"""Task state: the SPEC record, the status write, the reconcile rule matching and the status migration.

`task_report.py` renders this record, `task_gates.py` applies the transitions, `task_resolve.py`
finds it; the `## Status` contract is `task_status.py`. `normalize-status` rewrites only a legacy
token (`done` to `DONE`), keeps any suffix and reports each file; a second run finds nothing.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_progress import PROGRESS_FILE, append_transition, latest
from task_status import STATUS, StatusError, canonical, read_status, review_file
from task_status import head as state_head

from lib.files import atomic_write
from lib.git import slug_from_url


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


PREDICATES = {
    "all_checked": lambda r, rules: r.open == 0,
    "has_checkboxes": lambda r, rules: r.done > 0,
    "verdict_ok": lambda r, rules: r.verdict.lower() in ("pass", "warn"),
    "idle": lambda r, rules: r.age > rules["idle_days"],
}
KINDS = ("ready", "stalled", "hold")
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
    return TaskState(
        task=task, text=text, meta=meta, status=status.group(2).strip() if status else None,
        verdict=verdicts[-1] if verdicts else "?", age=days_since(newest_mtime(task)),
        open=len(OPEN_ITEM.findall(text)), done=len(DONE_ITEM.findall(text)),
        activity=days_since(last_activity(task)),
    )


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
