#!/usr/bin/env python3
"""Task state: the SPEC record, the status write, and the reconcile rule matching.

This module answers what a task is and what its next state is; `task_report.py` renders it,
`task_gates.py` applies the transitions, and `task_resolve.py` finds it. The `## Status` contract
itself stays in `task_status.py` and is re-exported here, so the entry points and the hooks keep one
reader.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Installed flat into ~/.agent/bin, but in the repo this file is `.agent/tools/task`; `resolve()`
# follows the installed symlink back into the repo, so one directory covers both. A hyphenated tool
# name cannot be imported, which is why the contract lives in a snake_case module.
for _dir in (Path(__file__).resolve().parent,):
    if (_dir / "task_status.py").is_file() and str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.files import atomic_write  # noqa: E402
from task_review import review_file  # noqa: E402
from task_status import STATUS, StatusError, head as state_head, read_status, token  # noqa: E402,F401  re-exported


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
    def modified(self) -> int:
        """Days since the newest activity file, the same value `age` holds."""
        return self.age

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
ACTIVITY_FILES = ("SPEC.md", "PROGRESS.md", "REVIEW.md", "REPORT.md")
LOG_PROGRESS = Path(__file__).resolve().parent / "crew-progress.py"


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


def load(task: Path) -> TaskState:
    """The record every consumer reads: identity, status, verdict, age, and checkbox counts."""
    spec = task / "SPEC.md"
    text = spec.read_text(encoding="utf-8")
    metadata = task / ".task-id"
    meta = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {}
    if not isinstance(meta, dict):
        meta = {}
    status = STATUS.search(text)
    review = review_file(task)
    verdicts = VERDICT.findall(review.read_text(encoding="utf-8")) if review else []
    newest = max((task / f).stat().st_mtime for f in ACTIVITY_FILES if (task / f).exists())
    return TaskState(
        task=task, text=text, meta=meta, status=status.group(2).strip() if status else None,
        verdict=verdicts[-1] if verdicts else "?",
        age=int((datetime.now(timezone.utc).timestamp() - newest) / 86400),
        open=len(OPEN_ITEM.findall(text)), done=len(DONE_ITEM.findall(text)),
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
    logged = subprocess.run([sys.executable, str(LOG_PROGRESS), str(r.task), transition],
                            capture_output=True, text=True)
    if logged.returncode != 0:
        print(f"warning: {name(r)}: PROGRESS.md not updated: {logged.stderr.strip()}",
              file=sys.stderr)
    print(f"applied: {name(r)} -> {value.split()[0]}")
    return True
