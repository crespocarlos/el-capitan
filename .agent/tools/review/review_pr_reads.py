"""The read half of `crew-pr-actions.py`: PR, repository, issue, and review-thread facts.

`read` prints one bare line per requested field; `threads` prints a flat object (`pageInfo`,
`threads`, three counts). A field gh did not return prints empty with exit 0; a failed call exits
nonzero with gh's stderr, and a failed thread fetch prints no JSON, so empty never means failed.
"""
from __future__ import annotations

import argparse
import json
import sys

import review_bootstrap  # noqa: F401

from lib.gh_reads import ALIASES, flag, read_argv
from lib.git import gh

THREADS_PATH = ("data", "repository", "pullRequest", "reviewThreads")
MAX_PAGES = 20
class ReadError(RuntimeError):
    """gh answered, but not with the record the call asked for."""


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
