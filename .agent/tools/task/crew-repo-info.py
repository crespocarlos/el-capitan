#!/usr/bin/env python3
"""Print the repository facts prompts need: root, branch, remote, and default branch.

Exits nonzero when an asked-for fact cannot be established, so empty never reads as an answer.
`--field NAME` prints one value bare; `--network` asks gh then git for the default branch (else the
local symref). `--diff-base` and `--fork-point` say where a branch's diff starts (`crew-diff.sh`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_repo_facts import collect

from lib.git import GitError, base_ref, fork_point

FIELDS = ("root", "branch", "head", "head_short", "dirty", "changed", "staged", "staged_dirty",
          "remote", "remote_url", "repo", "repo_name", "origin_repo", "default_branch")


def report(record: dict, as_json: bool) -> None:
    """The record as JSON, or as one `key: value` line per fact for a human reader."""
    if as_json:
        print(json.dumps(record, indent=2))
        return
    for key in FIELDS:
        print(f"{key}: {record[key]}")


def emit_field(record: dict, field: str) -> None:
    """One value on stdout, so a shell assignment cannot pick up a label or a second line."""
    value = record[field]
    if isinstance(value, list):
        print("\n".join(str(item) for item in value))
        return
    print("" if value is None else value)


def exit_code(record: dict, field: str | None, strict: bool) -> int:
    """0 when every fact asked for resolved, 1 when one did not.

    A null printed with exit 0 is the silent-empty answer this command exists to remove, so the
    *requested* fact decides: `--field X` fails when X is null, a full report fails when the branch
    is null, and `--strict` extends that to the default branch, which needs a network or a fetched
    symref and is therefore not always available.
    """
    if field is not None:
        if record[field] is not None:
            return 0
        print(f"repo-info: {field} is unavailable here", file=sys.stderr)
        return 1
    if record["branch"] is None:
        print("repo-info: no current branch; detached HEAD", file=sys.stderr)
        return 1
    if strict and record["default_branch"] is None:
        print(f"repo-info: the default branch of '{record['remote']}' is unknown", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print root, branch, remote, and default branch; JSON with --json.",
        epilog="Example: crew-repo-info.py --json --network  # resolve the default branch remotely",
    )
    parser.add_argument("--json", action="store_true", help="print the facts as JSON")
    parser.add_argument("--field", choices=FIELDS,
                        help="print only this value, bare, for a shell assignment")
    parser.add_argument("--root", type=Path, help="repository to read; default the current one")
    parser.add_argument("--remote", help="remote to report; default upstream, else origin")
    parser.add_argument("--network", action="store_true",
                        help="resolve the default branch over the network (gh, then git)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when the default branch cannot be resolved")
    parser.add_argument("--diff-base", action="store_true",
                        help="print the ref a branch diff starts from, instead of the record")
    parser.add_argument("--fork-point", action="store_true",
                        help="print where HEAD left the diff base, instead of the record")
    args = parser.parse_args()
    try:
        if args.diff_base:
            print(base_ref(args.root))
            return 0
        if args.fork_point:
            print(fork_point(args.root, base_ref(args.root)))
            return 0
    except GitError as error:
        print(f"repo-info: {error}", file=sys.stderr)
        return 1
    record = collect(args)
    if args.field:
        emit_field(record, args.field)
    else:
        report(record, args.json)
    return exit_code(record, args.field, args.strict)


if __name__ == "__main__":
    sys.exit(main())
