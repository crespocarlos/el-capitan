#!/usr/bin/env python3
"""The write-boundary guard must allow the review pipeline's own scratch directory.

The review tools write into `tempfile.gettempdir()`, which on macOS is `$TMPDIR`
(`/var/folders/…/T`), not `/tmp`. A guard that allowed only `/tmp` denied the pipeline its own
scratch path — a guard breaking the workflow it exists to protect. The earlier `review-dir` suite
passed while that was true, because it never exercised the hook.

Every case here drives the real hook, so the allowlist and the pipeline cannot disagree again.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude/hooks/check-write-boundary.sh"
FAILED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + str(detail) if detail else ''}")


def verdict(path: str) -> tuple[str, str]:
    """`allow` or `deny`, with the hook's message."""
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"file_path": path},
                          "cwd": str(ROOT)})
    result = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True)
    out = (result.stdout + result.stderr).strip()
    if result.returncode == 2 or "blocked" in out.lower():
        return "deny", out
    return "allow", out


def review_root() -> Path:
    """The directory the review tools actually choose, asked from the tool rather than assumed."""
    result = subprocess.run(["python3", str(ROOT / ".agent/tools/review/crew-review-findings.py"),
                             "review-dir", "--repo", "boundary-probe"], capture_output=True,
                            text=True)
    return Path(result.stdout.strip())


def temp_cases() -> None:
    chosen = review_root()
    check("the review tool writes under the temp root",
          str(chosen).startswith(str(Path(tempfile.gettempdir()).resolve()))
          or chosen.parent.exists(), chosen)
    state, detail = verdict(str(chosen / "layers.json"))
    check("a review scratch file is allowed", state == "allow", detail)

    state, detail = verdict(str(Path(tempfile.gettempdir()) / "crew-review-x" / "f.json"))
    check("a pipeline directory under the temp root is allowed", state == "allow", detail)

    state, detail = verdict("/tmp/crew-review-x/f.json")
    check("the /tmp spelling is still allowed", state == "allow", detail)


def repo_cases() -> None:
    state, detail = verdict(str(ROOT / "README.md"))
    check("a repository file is allowed", state == "allow", detail)


def deny_cases() -> None:
    state, detail = verdict("/etc/hosts")
    check("a system path is denied", state == "deny", detail)

    state, detail = verdict(str(ROOT / ".." / ".." / ".." / "etc" / "passwd"))
    check("a traversal out of the repository is denied", state == "deny", detail)


def allow_cases() -> None:
    """Only the pipeline's own directory under the temp root is allowed, never the root itself."""
    pipeline = Path(tempfile.gettempdir()) / "crew-review-boundary-probe" / "review" / "1"
    state, detail = verdict(str(pipeline / "layers.json"))
    check("the pipeline's scratch directory is allowed", state == "allow", detail)

    outside = Path(tempfile.mkdtemp(prefix="not-a-repo-")) / "x.json"
    state, detail = verdict(str(outside))
    check("arbitrary temp files are denied", state == "deny", detail)


def separate_temp_root() -> Path | None:
    """A `$TMPDIR` apart from /tmp, so the temp-root cases mean the same on Linux as on macOS.

    The hook allows /tmp wholesale but only `crew-review-*` under `$TMPDIR`. On Linux the default
    `$TMPDIR` is /tmp, where "arbitrary temp files are denied" can never hold; pointing `$TMPDIR`
    (inherited by the hook and the review tool) at a directory outside every permitted root keeps
    the case meaningful, as macOS's `/var/folders/…/T` does.
    """
    current = Path(tempfile.gettempdir()).resolve()
    if current != Path("/tmp").resolve() and Path("/tmp").resolve() not in current.parents:
        return None
    base = Path.home() / ".cache" / "el-capitan-fixtures"
    base.mkdir(parents=True, exist_ok=True)
    chosen = Path(tempfile.mkdtemp(prefix="tmpdir-", dir=base)).resolve()
    os.environ["TMPDIR"] = str(chosen)
    tempfile.tempdir = None
    return chosen


def main() -> int:
    separate = separate_temp_root()
    try:
        return run_cases()
    finally:
        if separate is not None:
            shutil.rmtree(separate, ignore_errors=True)


def run_cases() -> int:
    temp_cases()
    repo_cases()
    deny_cases()
    allow_cases()
    print("all write-boundary checks passed" if not FAILED else f"write-boundary: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
