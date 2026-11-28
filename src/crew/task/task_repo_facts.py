#!/usr/bin/env python3
"""Building the repository record a prompt reads: root, branch, head, remotes, and the file lists.

Every fact here is one call to `lib.git`, and each failing read is reported without discarding the
others: a detached HEAD or a missing remote leaves the root and the file lists usable, so the record
is still worth printing. Only the two reads a caller cannot proceed without — the root and the remote
names — raise, because without them every other field would answer about the wrong checkout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from crew.lib.cli import fail
from crew.lib.git import (
    GitError,
    current_branch,
    default_branch,
    dirty_files,
    head_sha,
    remote_url,
    remotes,
    repo_name_from_url,
    run_git,
    slug_from_url,
    staged_paths,
    toplevel,
    unstaged_paths,
)


def primary_remote(names: list[str]) -> str:
    """`upstream` when it exists, then `origin`, then the first configured remote.

    A fork's PR targets its upstream, so the preference that selects the PR base selects the remote
    this command reports; a checkout whose remote has another name still gets an answer.
    """
    for preferred in ("upstream", "origin"):
        if preferred in names:
            return preferred
    return names[0] if names else ""


def local_default(root: Path, remote: str) -> str | None:
    """The default branch from the local symref alone, so no request leaves the machine."""
    result = run_git(root, ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"], check=False)
    name = result.stdout.strip()
    return name.removeprefix(f"{remote}/") if result.returncode == 0 and name else None


def collect(args: argparse.Namespace) -> dict:
    """The record every caller reads: root, branch, head, the remotes, and the default branch."""
    try:
        root = toplevel(args.root)
        names = remotes(root)
    except GitError as error:
        fail(f"repo-info: {error}")
    remote = args.remote or primary_remote(names)
    urls = {name: remote_url(root, name) for name in names}
    record = {
        "root": str(root),
        "branch": None,
        "head": None,
        "head_short": None,
        "dirty": [],
        "changed": [],
        "staged": [],
        "staged_dirty": [],
        "remote": remote,
        "remote_url": urls.get(remote),
        "repo": slug_from_url(urls.get(remote)),
        "repo_name": repo_name_from_url(urls.get(remote)),
        "origin_repo": slug_from_url(urls.get("origin")),
        "remotes": {name: url for name, url in urls.items() if url},
        "default_branch": None,
    }
    try:
        record["branch"] = current_branch(root)
        record["head"] = head_sha(root)
        record["head_short"] = head_sha(root, short=True)
        record["dirty"] = dirty_files(root)
        record["changed"] = unstaged_paths(root)
        record["staged"] = staged_paths(root)
        record["staged_dirty"] = unstaged_paths(root, record["staged"])
    except GitError as error:
        print(f"repo-info: {error}", file=sys.stderr)
    if remote:
        record["default_branch"] = default_branch(root, remote) if args.network else local_default(root, remote)
    return record
