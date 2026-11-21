#!/usr/bin/env python3
"""The worktree subcommands that are not a resolve: list, fetch, sync, and remove.

Each is a call plus the output shape a prompt reads, so they live together rather than in the entry
point, which keeps to argument handling and exit codes. `--list` is the one a prompt parses, so it
answers JSON with each worktree's `path`, `branch`, `main`, `merged`, and `gone`, plus the `stale`
paths a cleanup may offer. `--remove` reports which half failed when the worktree goes but the
branch delete refuses, because a branch that survives its worktree is a decision, not an error.
"""
from __future__ import annotations

import argparse
import json
import sys

from lib.git import toplevel
from lib.output import bounded_json, truncate
from task_worktree_create import create, existing_worktree
from task_worktree_prune import prune_stale
from task_worktrees import fetch, listing, remove, stale, sync


def list_worktrees(args: argparse.Namespace) -> int:
    """Report every worktree, marking which ones a cleanup may offer."""
    entries = listing()
    payload = {"worktrees": entries, "stale": [entry["path"] for entry in entries if stale(entry)]}
    print(bounded_json(payload, args.max_chars, what="worktrees"))
    return 0


def remove_worktree(args: argparse.Namespace) -> int:
    """Remove a worktree and, when named, its branch; both refusals reach the caller."""
    if args.dry_run:
        print(f"dry-run: git worktree remove {args.remove}", file=sys.stderr)
        return 0
    code, message = remove(args.remove, args.branch, force_branch=args.force)
    print(message, file=sys.stdout if code == 0 else sys.stderr)
    return code


def run_operation(args: argparse.Namespace) -> int:
    """Dispatch one non-resolve operation, so `main` stays an error-handling shell."""
    if args.list:
        return list_worktrees(args)
    if args.remove is not None:
        return remove_worktree(args)
    if args.operation == "fetch":
        print(f"fetched {fetch()}")
        return 0
    print(sync(args.branch))
    return 0


def is_operation(args: argparse.Namespace) -> bool:
    """True when the invocation asks for one of the operations rather than a resolve."""
    return bool(args.list or args.remove is not None or args.operation in {"fetch", "sync"})


def worktree_path(args: argparse.Namespace, path: str) -> None:
    """Print a resolved worktree path, as JSON under `--json`, bounded by `--max-chars`."""
    text = json.dumps({"path": path, "branch": args.branch_name}) if args.json else path
    print(truncate(text, args.max_chars, what="worktree path"))


def resolve(args: argparse.Namespace) -> int:
    """Resolve an existing worktree for the branch, or create one."""
    prune_stale(args.dry_run)
    top = toplevel(None)
    found = existing_worktree(args.branch_name, top)
    if found:
        worktree_path(args, found)
        return 0
    if args.dry_run:
        print(f"dry-run: create a worktree for {args.branch_name}", file=sys.stderr)
    code, result = create(args.branch_name, args.base if args.new_branch else None, top)
    if code:
        if result:
            print(result, file=sys.stderr)
        return code
    worktree_path(args, result)
    return 0
