#!/usr/bin/env python3
"""`memory_paths.repo_key`: the memory scope a checkout resolves to, pinned per remote shape.

A key that changes orphans every unit stored under the old one, so each shape keeps its key: the
repository name for an https, ssh, scp (with or without a user) or git:// remote, the last path
segment for a local path or file:// remote, and the checkout's directory name when there is no remote.
`crew-repo-info.py --field repo_name` must give the same name for every remote, because crew-recall
scopes by it while the store scopes by `repo_key`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEMORY = ROOT / ".agent" / "tools" / "memory"
FAILED: list[str] = []
# (case, origin URL or None, the key repo_key must return for a checkout named "checkout")
CASES = (
    ("https remote", "https://github.com/acme/gadgets.git", "gadgets"),
    ("scp remote", "git@github.com:acme/gizmos.git", "gizmos"),
    ("ssh:// remote", "ssh://git@github.com/acme/sprockets.git", "sprockets"),
    ("ssh-alias remote (no user)", "github-work:acme/cogs.git", "cogs"),
    ("git:// remote", "git://github.com/acme/levers", "levers"),
    ("local-path remote", "/srv/git/widgets.git", "widgets"),
    ("file:// remote", "file:///srv/git/tools.git", "tools"),
    ("no remote", None, "checkout"),
)


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("pass: " if condition else "FAIL: ") + name + ("" if condition else f": {detail}"))
    if not condition:
        FAILED.append(name)


def git(cwd: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True)


def keys_in(checkout: Path) -> tuple[str, str]:
    """`(repo_key(), repo_name)` as one fresh interpreter in `checkout` computes them (cwd decides the repository).

    `repo_name` is the field `crew-repo-info.py --field repo_name` prints (`task_repo_facts.collect`).
    """
    env = {**os.environ, "PYTHONPATH": str(MEMORY), "GIT_CONFIG_GLOBAL": os.devnull}
    program = ("import argparse, memory_bootstrap, memory_paths, task_repo_facts\n"
               "facts = task_repo_facts.collect(argparse.Namespace(root=None, remote=None, network=False))\n"
               "print(memory_paths.repo_key()); print(facts['repo_name'])")
    result = subprocess.run([sys.executable, "-c", program], cwd=checkout, env=env, capture_output=True, text=True,
                            timeout=60)
    lines = result.stdout.split("\n")
    return (lines[0], lines[1]) if len(lines) > 2 else (result.stderr.strip(), result.stderr.strip())


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        for index, (case, url, expected) in enumerate(CASES):
            checkout = Path(temp) / str(index) / "checkout"
            checkout.mkdir(parents=True)
            git(checkout, "init", "-q")
            if url:
                git(checkout, "remote", "add", "origin", url)
            found, named = keys_in(checkout)
            check(f"{case}: key is {expected}", found == expected, found)
            if url:
                check(f"{case}: repo_name is the same {expected}", named == expected, named)
    print("memory-repo-key: fail" if FAILED else "memory-repo-key: pass")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
