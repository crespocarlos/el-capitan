"""Git and GitHub helpers: one runner per command family.

`run_git` takes the repository it should act on, so a tool that reads a checkout other than its
own passes it explicitly instead of relying on the current directory. `gh` is the single GitHub
invocation: it captures both streams so a caller reports GitHub's own error text unchanged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """git could not answer; the payload is git's own stderr or its exit status."""


def run_git(
    root: Path | None, arguments: list[str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run git in `root`, or in the current directory when `root` is None."""
    command = ["git", *(["-C", str(root)] if root is not None else []), *arguments]
    return subprocess.run(command, text=True, capture_output=True, check=check)


def dirty_files(root: Path | None) -> list[str]:
    """Every path git reports as changed, including untracked files."""
    result = run_git(root, ["status", "--porcelain"], check=True)
    return [line for line in result.stdout.splitlines() if line]


def conflicted_paths(root: Path | None) -> list[str]:
    """Conflicted paths, or GitError when git cannot answer.

    A failed `git diff` (broken index, missing repo, held lock) is not "no conflicts":
    reporting clean would let a caller adopt conflict markers as a resolution.
    """
    result = run_git(root, ["diff", "--name-only", "--diff-filter=U"], check=False)
    if result.returncode:
        raise GitError(result.stderr.strip() or f"git exit {result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def gh(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run gh with both streams captured, so a caller surfaces its own error text."""
    return subprocess.run(
        ["gh", *arguments], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
