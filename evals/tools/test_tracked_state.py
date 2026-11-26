#!/usr/bin/env python3
"""Per-run state under `.agent/` must never be tracked by git.

Two task artifacts were committed by an earlier `git add -A` and swept away by a later one, which
made an unrelated docs commit carry their deletion. `.gitignore` owns the rule; this suite proves the
lint check catches a regression, using a throwaway repository so the real tree is never touched.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agent" / "tools" / "maintenance"))
from lint_writing import lint_local_state_tracked  # noqa: E402

FAILED: list[str] = []
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + str(detail) if detail else ''}")


def git(scratch: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(scratch), *args], capture_output=True, text=True,
                          env=ENV)


def build(scratch: Path) -> None:
    git(scratch, "init", "-q")
    (scratch / ".agent" / "tools").mkdir(parents=True)
    (scratch / ".agent" / "tools" / "keep.py").write_text("x\n", encoding="utf-8")
    (scratch / ".agent" / "_SPEC_TEMPLATE.md").write_text("t\n", encoding="utf-8")
    (scratch / ".agent" / "tasks" / "abc").mkdir(parents=True)
    (scratch / ".agent" / "tasks" / "abc" / "SPEC.md").write_text("leaked\n", encoding="utf-8")
    (scratch / ".agent" / "reviews").mkdir(parents=True)
    (scratch / ".agent" / "reviews" / "note.md").write_text("leaked\n", encoding="utf-8")


def cases() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="lint-state-"))
    try:
        build(scratch)
        git(scratch, "add", "-f", ".agent")
        found = {path for path, _, kind, _ in lint_local_state_tracked(scratch)
                 if kind == "tracked-local-state"}
        check("a tracked task spec is reported", any("tasks/" in p for p in found), found)
        check("a tracked review note is reported", any("reviews/" in p for p in found), found)
        check("the tool tree is not reported", not any("/tools/" in p for p in found), found)
        check("a template is not reported", not any("_SPEC_TEMPLATE" in p for p in found), found)

        git(scratch, "rm", "-r", "--cached", "-q", ".agent/tasks", ".agent/reviews")
        check("untracked state passes", lint_local_state_tracked(scratch) == [],
              lint_local_state_tracked(scratch))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def real_tree() -> None:
    """The repository itself must be clean, which is what makes the check worth running."""
    check("the real tree has no tracked local state", lint_local_state_tracked(ROOT) == [],
          lint_local_state_tracked(ROOT))


def gitignore_covers_it() -> None:
    """`.agent/*` is ignored with the templates and tool tree re-included."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("gitignore ignores .agent children", ".agent/*" in text, text[:200])
    for exception in ("!.agent/tools/", "!.agent/_SPEC_TEMPLATE.md"):
        check(f"gitignore re-includes {exception}", exception in text)


def main() -> int:
    cases()
    real_tree()
    gitignore_covers_it()
    print("all tracked-state checks passed" if not FAILED else f"tracked-state: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
