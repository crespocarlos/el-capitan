#!/usr/bin/env python3
"""Task state: the SPEC record, the status write, and the reconcile rule matching.

This module answers what a task is and what its next state is; `task_report.py` renders it,
`task_gates.py` applies the transitions, and `task_resolve.py` finds it. The `## Status` contract
itself stays in `task_status.py` and is re-exported here, so the entry points and the hooks keep one
reader.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Installed flat into ~/.agent/bin, but in the repo this file is `.agent/tools/task`; `resolve()`
# follows the installed symlink back into the repo, so one directory covers both. A hyphenated tool
# name cannot be imported, which is why the contract lives in a snake_case module.
for _dir in (Path(__file__).resolve().parent,):
    if (_dir / "task_status.py").is_file() and str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
from task_status import STATUS, head as state_head, read_status  # noqa: E402,F401  re-exported


def head(r: dict) -> str:
    """The normalized state token of a loaded task record (the contract's `head` over its status)."""
    return state_head(r["status"])


PREDICATES = {
    "all_checked": lambda r, rules: r["open"] == 0,
    "has_checkboxes": lambda r, rules: r["done"] > 0,
    "verdict_ok": lambda r, rules: r["verdict"].lower() in ("pass", "warn"),
    "idle": lambda r, rules: r["age"] > rules["idle_days"],
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


def load_rules() -> dict:
    """The transitions file, validated so a malformed rule aborts instead of silently matching."""
    path = Path(__file__).resolve().parent / "transitions.json"
    try:
        rules = json.loads(path.read_text())
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
        print(f"error: {path.name}: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(2)
    return rules


def name(r: dict) -> str:
    return r["meta"].get("slug", r["task"].name)


def load(task: Path) -> dict:
    """The record every consumer reads: identity, status, verdict, age, and checkbox counts."""
    spec = task / "SPEC.md"
    text = spec.read_text()
    meta = json.loads((task / ".task-id").read_text()) if (task / ".task-id").exists() else {}
    if not isinstance(meta, dict):
        meta = {}
    status = STATUS.search(text)
    verdicts = VERDICT.findall((task / "REVIEW.md").read_text()) if (task / "REVIEW.md").exists() else []
    newest = max((task / f).stat().st_mtime for f in ACTIVITY_FILES if (task / f).exists())
    return dict(task=task, text=text, meta=meta, status=status.group(2).strip() if status else None,
                verdict=verdicts[-1] if verdicts else "?",
                age=int((datetime.now(timezone.utc).timestamp() - newest) / 86400),
                open=len(OPEN_ITEM.findall(text)), done=len(DONE_ITEM.findall(text)))


def decide(r: dict, rules: dict) -> dict | None:
    """The first transition rule that matches this spec, or None."""
    for rule in rules["auto"]:
        if head(r) in rule["from"] and all(PREDICATES[p](r, rules) for p in rule["when"]):
            return rule
    return None


def set_status(r: dict, value: str, transition: str) -> bool:
    """Write the new `## Status` value, refusing when the spec changed since it was read."""
    spec = r["task"] / "SPEC.md"
    tmp = spec.with_name("SPEC.md.tmp")
    try:
        current = spec.read_text()
        if current != r["text"]:
            raise OSError("SPEC.md changed since it was read")
        updated, count = STATUS.subn(lambda m: m.group(1) + value, current, count=1)
        if count != 1:
            raise OSError("no Status value found")
        tmp.write_text(updated)
        os.replace(tmp, spec)
    except OSError as error:
        tmp.unlink(missing_ok=True)
        print(f"error: {name(r)}: {error}", file=sys.stderr)
        return False
    logged = subprocess.run([sys.executable, str(LOG_PROGRESS), str(r["task"]), transition],
                            capture_output=True, text=True)
    if logged.returncode != 0:
        print(f"warning: {name(r)}: PROGRESS.md not updated: {logged.stderr.strip()}",
              file=sys.stderr)
    print(f"applied: {name(r)} -> {value.split()[0]}")
    return True
