#!/usr/bin/env python3
"""Print the repository facts prompts need: root, branch, remote, and default branch.

One question, one command. A prompt that shells out to `git rev-parse`, `git remote get-url`, or
`git branch --show-current` reads an empty string when git fails and then acts on it — a wrong branch
name or a wrong diff base. This prints the same facts as data and exits nonzero when a fact it was
asked for cannot be established.

`--network` resolves the default branch through `gh` first and `git` second, because gh carries the
authentication. Without it the answer comes from the local `refs/remotes/<remote>/HEAD` symref only,
so a prompt that needs just the root or the branch costs no round trip.

`--field` prints one value bare, so a prompt can assign what it needs (`BRANCH=$(... --field
branch)`) instead of parsing a listing. `changed` and `staged` are the two name lists a prompt falls
back to when it needs the files to test; `head_short` and `dirty` carry the two facts a handoff
records, so a resumed session compares the same source rather than re-deriving them.

`--diff-base` and `--fork-point` answer the other question a prompt used to ask git directly: where a
branch's diff starts. `crew-diff.sh` captures them, so the ref order has one implementation and one
test rather than a shell copy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from lib.git import GitError, base_ref, fork_point  # noqa: E402
from task_repo_facts import collect  # noqa: E402

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
