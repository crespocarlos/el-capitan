"""The read half of `crew-pr-actions.py`: PR, repository, issue, and review-thread facts.

A prompt cannot call `lib/git.py`, so every prompt read used to spell out a `gh pr view --json …`
plus its own `--jq`, and each copy re-decided which fields exist. These reads live here once. `read`
answers one question per invocation and prints one bare line per field in the order asked; `threads`
prints review threads as a flat object — `pageInfo`, `threads`, and the three counts a caller used
to filter for — instead of gh's raw GraphQL envelope.

Absence is quiet and failure is loud, the rule `crew-repo-info.py` follows. A field gh did not
return prints empty and the exit code stays 0, so a caller can test it; a failed call exits nonzero
carrying gh's own stderr, so an error is never read as an empty answer. A failed thread fetch prints
no JSON at all, because an empty list is also the real answer for a PR nobody has reviewed yet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from lib.git import gh  # noqa: E402

THREADS_PATH = ("data", "repository", "pullRequest", "reviewThreads")
MAX_PAGES = 20
ALIASES = {"branch": "headRefName"}
DEFAULT_FIELDS = {"view": "number,url,title,state,isDraft,headRefName,headRefOid,baseRefName",
                 "repo": "nameWithOwner", "issue": "title,body"}


class ReadError(RuntimeError):
    """gh answered, but not with the record the call asked for."""


def field_list(value: str) -> list[str]:
    """`branch,title,files` as three names, so spaces and a trailing comma are harmless."""
    return [name.strip() for name in value.split(",") if name.strip()]


def gh_fields(fields: list[str]) -> list[str]:
    """The `--json` names for the fields asked for; `branch` is the one alias gh lacks."""
    return [ALIASES.get(name, name) for name in fields]


def flag(option: str, value: object) -> list[str]:
    """`[option, value]`, or nothing when the value is absent, so gh falls back to the checkout."""
    return [option, str(value)] if value not in (None, "") else []


def item_text(value: object) -> str:
    """One list item: its name where it has one, else compact JSON."""
    if isinstance(value, dict):
        for key in ("path", "name", "login"):
            if isinstance(value.get(key), str):
                return value[key]
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return json.dumps(text) if "\n" in text else text


def value_text(value: object) -> str:
    """One field as one line. A value holding a newline is JSON-quoted, so the shape holds."""
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(item_text(item) for item in value)
    return item_text(value)


def read_argv(command: str, args: argparse.Namespace) -> list[str]:
    """The exact `gh` argv for one read.

    gh takes the PR and issue numbers positionally and `--repo` as its scope flag, so the argv mirrors
    that rather than inventing options gh does not have. An absent `--repo` or number lets gh resolve
    the current checkout, which is how a prompt asks about its own branch.
    """
    repo = flag("--repo", args.repo)
    number = [str(args.pr)] if getattr(args, "pr", None) is not None else []
    if command == "diff":
        argv = ["pr", "diff", *number, *repo]
        return [*argv, "--name-only"] if args.name_only else argv
    fields = ",".join(gh_fields(args.field))
    if command == "repo":
        return ["repo", "view", *repo, "--json", fields]
    if command == "issue":
        return ["issue", "view", str(args.number), *repo, "--json", fields]
    return ["pr", "view", *number, *repo, "--json", fields]


def read(command: str, args: argparse.Namespace) -> int:
    """Run one read: the patch verbatim for `diff`, else the whole record or one line per field."""
    result = gh(*read_argv(command, args))
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    if command == "diff":
        sys.stdout.write(result.stdout)
        return 0
    try:
        record = json.loads(result.stdout)
    except ValueError as error:
        print(f"pr-actions: {command} returned no JSON ({error})", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(record, indent=2))
        return 0
    for name in args.field:
        print(value_text(record.get(ALIASES.get(name, name))))
    return 0


def add_read_parser(commands: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    """One read verb: `--repo` when the checkout is not the target, plus the fields it prints."""
    action = commands.add_parser(name)
    action.add_argument("--repo", help="OWNER/REPO; default the checkout's own repository")
    if name == "issue":
        action.add_argument("--number", required=True, type=int)
    else:
        action.add_argument("--pr", type=int, help="PR number; default the current branch's")
    if name == "diff":
        action.add_argument("--name-only", action="store_true", help="changed paths, one per line")
        return action
    action.add_argument("--json", action="store_true",
                        help="the fetched record as JSON, not one bare line per field")
    action.add_argument("--field", type=field_list, default=field_list(DEFAULT_FIELDS[name]),
                        help="comma-separated names; one bare line each, in this order")
    return action


def page_of(payload: dict) -> dict:
    """The `reviewThreads` object, or ReadError naming the path that was absent."""
    node: object = payload
    for key in THREADS_PATH:
        if not isinstance(node, dict) or key not in node:
            raise ReadError(f"gh's response has no {'.'.join(THREADS_PATH)}")
        node = node[key]
    if not isinstance(node, dict):
        raise ReadError(f"{'.'.join(THREADS_PATH)} is {type(node).__name__}, not an object")
    return node


def tally(merged: list[dict]) -> dict[str, int]:
    """The three counts callers filter for, over the merged set rather than one page."""
    def unresolved(thread: dict) -> bool:
        return not thread.get("isResolved")

    return {"resolved": sum(1 for t in merged if t.get("isResolved")),
            "unresolvedCurrent": sum(1 for t in merged if unresolved(t) and not t.get("isOutdated")),
            "unresolvedOutdated": sum(1 for t in merged if unresolved(t) and t.get("isOutdated"))}


def one_page(command: list[str], cursor: str | None) -> dict:
    """One page of review threads; every way it can fail raises ReadError with gh's own text."""
    result = gh(*command, *flag("-f", f"cursor={cursor}" if cursor else None))
    if result.returncode:
        raise ReadError(result.stderr.strip() or f"gh exit {result.returncode}")
    try:
        payload = json.loads(result.stdout)
    except ValueError as error:
        raise ReadError(f"gh returned no JSON ({error})") from error
    if payload.get("errors"):
        raise ReadError(json.dumps(payload["errors"]))
    return page_of(payload)


def threads(command: list[str], cursor: str | None) -> int:
    """Every page from `cursor` on, merged, flat, with the counts taken over the whole set."""
    merged: list[dict] = []
    more, pages = True, 0
    while more:
        try:
            page = one_page(command, cursor)
        except ReadError as error:
            print(f"pr-actions: {error}", file=sys.stderr)
            return 1
        merged.extend(page.get("nodes") or [])
        info = page.get("pageInfo") or {}
        more, pages = bool(info.get("hasNextPage")), pages + 1
        cursor = info.get("endCursor") or cursor
        if more and pages >= MAX_PAGES:
            print(f"pr-actions: stopped after {MAX_PAGES} pages with more threads left; resume "
                  f"with --cursor {cursor}", file=sys.stderr)
            break
    print(json.dumps({"pageInfo": {"hasNextPage": more, "endCursor": cursor},
                      "threads": merged, **tally(merged)}, indent=2))
    return 0
