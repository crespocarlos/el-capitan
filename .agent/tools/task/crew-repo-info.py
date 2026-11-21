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
branch)`) instead of parsing a listing. `head_short` and `dirty` carry the two facts a handoff
records, so a resumed session compares the same source rather than re-deriving them.

`--diff-base` and `--fork-point` answer the other question a prompt used to ask git directly: where a
branch's diff starts. `crew-diff.sh` captures them, so the ref order has one implementation and one
test rather than a shell copy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from lib.git import (  # noqa: E402
    GitError,
    base_ref,
    current_branch,
    default_branch,
    dirty_files,
    fork_point,
    head_sha,
    remotes,
    remote_url,
    run_git,
    staged_paths,
    toplevel,
    unstaged_paths,
)

SLUG = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/*$")
FIELDS = ("root", "branch", "head", "head_short", "dirty", "staged", "staged_dirty", "remote",
          "remote_url", "repo", "repo_name", "origin_repo", "default_branch")


def primary_remote(names: list[str]) -> str:
    """`upstream` when it exists, then `origin`, then the first configured remote.

    A fork's PR targets its upstream, so the preference that selects the PR base selects the remote
    this command reports; a checkout whose remote has another name still gets an answer.
    """
    for preferred in ("upstream", "origin"):
        if preferred in names:
            return preferred
    return names[0] if names else ""


def slug_of(url: str | None) -> str | None:
    """The `owner/repo` a remote URL names, or None when the URL carries no such path."""
    if not url:
        return None
    match = SLUG.search(url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def local_default(root: Path, remote: str) -> str | None:
    """The default branch from the local symref alone, so no request leaves the machine."""
    result = run_git(root, ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"],
                     check=False)
    name = result.stdout.strip()
    return name.removeprefix(f"{remote}/") if result.returncode == 0 and name else None


def collect(args: argparse.Namespace) -> dict:
    """The record every caller reads: root, branch, head, the remotes, and the default branch."""
    try:
        root = toplevel(args.root)
        names = remotes(root)
    except GitError as error:
        raise SystemExit(f"repo-info: {error}") from error
    remote = args.remote or primary_remote(names)
    urls = {name: remote_url(root, name) for name in names}
    record = {
        "root": str(root),
        "branch": None,
        "head": None,
        "head_short": None,
        "dirty": [],
        "staged": [],
        "staged_dirty": [],
        "remote": remote,
        "remote_url": urls.get(remote),
        "repo": slug_of(urls.get(remote)),
        "repo_name": (slug_of(urls.get(remote)) or "/").split("/")[-1] or None,
        "origin_repo": slug_of(urls.get("origin")),
        "remotes": {name: url for name, url in urls.items() if url},
        "default_branch": None,
    }
    try:
        record["branch"] = current_branch(root)
        record["head"] = head_sha(root)
        record["head_short"] = head_sha(root, short=True)
        record["dirty"] = dirty_files(root)
        record["staged"] = staged_paths(root)
        record["staged_dirty"] = unstaged_paths(root, record["staged"])
    except GitError as error:
        print(f"repo-info: {error}", file=sys.stderr)
    if remote:
        record["default_branch"] = (default_branch(root, remote) if args.network
                                    else local_default(root, remote))
    return record


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
