#!/usr/bin/env python3
"""Checks for `review-dir`: the task directory when writable, a temp path when it is not.

The defect this guards is specific: the pipeline used to fall back only when no task was resolved,
so a sandbox that resolved the task and then denied the write left the review with nowhere to go.
Every case here drives the decision by making a directory unwritable rather than by mocking a
predicate, because the original bug was a predicate that could not observe the failure.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / ".agent" / "tools" / "review"
CLI = REVIEW / "crew-review-findings.py"

FAILED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + str(detail) if detail else ''}")


def load_workspace():
    sys.path.insert(0, str(REVIEW))
    spec = importlib.util.spec_from_file_location("review_workspace", REVIEW / "review_workspace.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*arguments: str) -> tuple[int, str, str]:
    result = subprocess.run([sys.executable, str(CLI), "review-dir", *arguments],
                            capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def writable_task() -> Path:
    """A task directory this process may write, under the workspace so no sandbox denies it."""
    base = Path(tempfile.mkdtemp(prefix="review-dir-", dir=ROOT / "evals"))
    (base / ".task-id").write_text(json.dumps({"slug": "probe"}), encoding="utf-8")
    return base


def read_only(path: Path) -> None:
    path.chmod(0o500)


def restore(path: Path) -> None:
    try:
        path.chmod(0o700)
    except OSError:
        pass


def temp_root(repo: str) -> Path:
    return Path(tempfile.gettempdir()) / f"crew-review-{repo}"


def task_cases(workspace) -> None:
    """The task directory wins when it can be written."""
    task = writable_task()
    try:
        chosen = workspace.review_dir(str(task), "probe", "self")
        check("a writable task directory is chosen", str(chosen).startswith(str(task)), chosen)
        check("the review directory exists", chosen.is_dir(), chosen)
        check("no write probe is left behind", not (chosen / ".write-probe").exists())
    finally:
        restore(task)
        shutil.rmtree(task, ignore_errors=True)

    code, out, err = run("--task-dir", str(task), "--repo", "probe")
    check("the command prints the path and exits 0", code == 0 and out.strip() != "", (code, out))
    check("a task-based path says nothing on stderr", err.strip() == "", err)


def fallback_cases(workspace) -> None:
    """An unwritable task directory falls back to a temp path that names the repo."""
    task = writable_task()
    try:
        read_only(task)
        chosen = workspace.review_dir(str(task), "probe", "self")
        check("an unwritable task directory falls back", str(task) not in str(chosen), chosen)
        check("the fallback names the repo", "crew-review-probe" in str(chosen), chosen)
        check("the fallback exists", chosen.is_dir(), chosen)
    finally:
        restore(task)
        shutil.rmtree(task, ignore_errors=True)


def pr_cases(workspace) -> None:
    """PR mode never touches the task directory, even when it is writable."""
    task = writable_task()
    try:
        chosen = workspace.review_dir(str(task), "probe", "pr")
        check("a pr review ignores a writable task directory", str(task) not in str(chosen), chosen)
    finally:
        shutil.rmtree(task, ignore_errors=True)

    code, out, err = run("--task-dir", str(task), "--mode", "pr", "--repo", "probe")
    check("pr mode still exits 0", code == 0 and out.strip() != "", (code, out))


def report_cases() -> None:
    """The reason for a fallback reaches stderr, never the captured stdout."""
    code, out, err = run("--repo", "probe-unwritable", "--task-dir", "/nonexistent/task")
    check("an unusable task directory still yields a path", code == 0 and out.strip() != "", (code, out))
    check("the fallback reason is on stderr", "not writable" in err, err)
    check("stdout holds only the path", len(out.strip().splitlines()) == 1, out)


def prune_cases(workspace) -> None:
    """`--prune` keeps the newest ten and removes older siblings."""
    base = Path(tempfile.mkdtemp(prefix="review-prune-"))
    keep = base / "99999999999999"
    keep.mkdir()
    for index in range(14):
        sibling = base / f"202601010000{index:02d}"
        sibling.mkdir()
        (sibling / "artifact.json").write_text("{}", encoding="utf-8")
    removed = workspace.cleanup_stale(base, keep)
    remaining = sorted(p.name for p in base.iterdir() if p.is_dir())
    check("pruning removes the older siblings", len(removed) == 4, removed)
    check("pruning keeps ten", len(remaining) == 11, remaining)
    check("pruning keeps the current directory", keep.name in remaining, remaining)
    shutil.rmtree(base, ignore_errors=True)


def claim_cases(workspace) -> None:
    """A new directory records what it is, and does not pretend to have paths yet."""
    task = writable_task()
    try:
        chosen = workspace.review_dir(str(task), "probe", "self")
        workspace.claim(chosen, "self", "probe", str(task))
        record = json.loads((chosen / "run.json").read_text(encoding="utf-8"))
        check("run.json records the mode", record.get("mode") == "self", record)
        check("run.json records the repo", record.get("repo") == "probe", record)
        check("run.json records the task directory", record.get("task_dir") == str(task), record)
        check("run.json records when it was created", bool(record.get("created")), record)
        check("paths.txt is absent until the diff step", not (chosen / "paths.txt").exists(),
              sorted(p.name for p in chosen.iterdir()))
    finally:
        restore(task)
        shutil.rmtree(task, ignore_errors=True)


def main() -> int:
    workspace = load_workspace()
    task_cases(workspace)
    fallback_cases(workspace)
    pr_cases(workspace)
    report_cases()
    prune_cases(workspace)
    claim_cases(workspace)
    print("all review-dir checks passed" if not FAILED else f"review-dir: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
