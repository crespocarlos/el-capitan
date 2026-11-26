#!/usr/bin/env python3
"""Resolve or create a git worktree, and answer what the other worktrees are.

With a branch it resolves or creates that branch's worktree, pruning stale registrations first
(`crew implement`); `--list` reports every worktree as JSON (`crew cleanup`); `fetch`, `sync` and
`--remove` refresh the remote, check a branch out, and remove a worktree with its branch.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_worktree_cli import is_operation, resolve, run_operation

from lib.git import GitError
from lib.output import DEFAULT_MAX_CHARS

OPERATIONS = ("resolve", "fetch", "sync")

USAGE = """crew-worktree.py [OPERATION] [BRANCH] [BASE]

Resolve or create one branch's worktree, or answer what the registered worktrees are.

operations:
  (default)             resolve BRANCH's worktree, creating it when absent
  --list                every worktree: path, branch, merged, gone, main (JSON)
  fetch                 refresh the remote's refs and prune deleted branches
  sync --branch NAME    fetch NAME and check it out here, creating it if needed
  --remove PATH         remove that worktree, and its branch with --branch NAME

`crew-worktree.py resolve fetch` reaches a branch literally named `fetch` or `sync`.
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """The flags, with the first positional read as an operation or a branch."""
    parser = argparse.ArgumentParser(
        prog="crew-worktree.py", usage=USAGE, add_help=True,
        description="Resolve, create, list, sync, or remove worktrees.")
    parser.add_argument("operation", nargs="?", default=None,
                        help="what to do: fetch, sync, or resolve; default resolves BRANCH")
    parser.add_argument("-b", "--new-branch", action="store_true", help="create branch from BASE")
    parser.add_argument("--list", action="store_true", help="report every worktree as JSON")
    parser.add_argument("--remove", type=Path, help="remove this worktree")
    parser.add_argument("--branch", help="branch to sync or to delete with --remove")
    parser.add_argument("--force", action="store_true",
                        help="with --remove, delete the branch even when unmerged")
    parser.add_argument("--dry-run", action="store_true",
                        help="print mutating actions without running them")
    parser.add_argument("--json", action="store_true", help="print the path as JSON on stdout")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"bound stdout past N chars with a marker (default {DEFAULT_MAX_CHARS})")
    parser.add_argument("positional_branch", nargs="?", help="branch to resolve or create")
    parser.add_argument("base", nargs="?", help="base ref; required with --new-branch")
    args = parser.parse_args(argv)
    split_positionals(args)
    if args.max_chars < 1:
        parser.error("--max-chars must be at least 1")
    if not is_operation(args):
        if args.operation == "sync" and not args.branch:
            parser.error("sync requires --branch NAME")
        if not args.branch_name:
            parser.error("branch is required")
    if args.new_branch and not args.base:
        parser.error("--new-branch requires BASE")
    return args


def split_positionals(args: argparse.Namespace) -> None:
    """Read the first positional as an operation when it names one, else as the branch.

    `crew-worktree.py main` resolves the branch named `main`, so a branch that happens to be called
    `fetch` or `sync` is reached with the explicit `resolve` operation.
    """
    first, rest = args.operation, args.positional_branch
    if first in OPERATIONS:
        args.operation, args.positional_branch = first, None
        if rest is not None:
            args.base = rest
    elif first is not None:
        args.operation, args.positional_branch = "resolve", first
        if rest is not None:
            args.base = rest
    else:
        args.operation = "resolve"
    args.branch_name = args.branch or args.positional_branch


def main() -> int:
    args = parse_args()
    try:
        return run_operation(args) if is_operation(args) else resolve(args)
    except GitError as error:
        print(f"manage-worktree: {error}", file=sys.stderr)
        return 2
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"manage-worktree: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
