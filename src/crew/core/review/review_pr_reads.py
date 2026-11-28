"""PR, repository, issue, and review-thread facts: `crew-tool.py pr-read` and `crew-pr-actions.py fetch`.

`pr_read` returns the fields asked for; `threads` prints a flat object (`pageInfo`, `threads`, three
counts). A field gh did not return is absent; a failed call raises with gh's stderr, and a failed thread
fetch prints no JSON, so empty never means failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Literal

from crew.lib.errors import ToolError
from crew.lib.gh_reads import ALIASES, DEFAULT_FIELDS, field_list, flag, read_argv
from crew.lib.git import gh

THREADS_PATH = ("data", "repository", "pullRequest", "reviewThreads")
MAX_PAGES = 20


class ReadError(RuntimeError):
    """gh answered, but not with the record the call asked for."""


@dataclass
class PrRecord:
    """One gh read: the record's fields (view, repo, issue) or the patch (diff)."""

    kind: str
    record: dict
    diff: str = ""


def pr_read(kind: Literal["view", "diff", "repo", "issue"], repo: str = "", pr: int = 0, number: int = 0, fields: str = "") -> PrRecord:
    """A PR, its diff, a repository or an issue, read through gh; a field gh did not return is absent.

    Args:
        kind: view (a PR), diff (its patch), repo (a repository) or issue
        repo: OWNER/REPO (default: the checkout's)
        pr: the PR number (default: the current branch's)
        number: the issue number (issue)
        fields: comma-separated gh JSON fields (view, repo, issue)
    """
    if kind == "issue" and not number:
        raise ToolError("usage", "issue needs --number", "arguments", exit=2)
    names = field_list(fields or DEFAULT_FIELDS.get(kind, ""))
    asked = argparse.Namespace(repo=repo, pr=pr or None, number=number, field=names, name_only=False)
    result = gh(*read_argv(kind, asked))
    if result.returncode:
        raise ToolError("gh", result.stderr.strip() or f"gh exit {result.returncode}", f"pr {kind}", "check `gh auth status` and the repo", result.returncode)
    if kind == "diff":
        return PrRecord(kind, {}, result.stdout)
    try:
        record = json.loads(result.stdout)
    except ValueError as error:
        raise ToolError("gh", f"{kind} returned no JSON ({error})", f"pr {kind}") from error
    return PrRecord(kind, {name: record.get(ALIASES.get(name, name)) for name in names})


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

    return {
        "resolved": sum(1 for t in merged if t.get("isResolved")),
        "unresolvedCurrent": sum(1 for t in merged if unresolved(t) and not t.get("isOutdated")),
        "unresolvedOutdated": sum(1 for t in merged if unresolved(t) and t.get("isOutdated")),
    }


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
            print(f"pr-actions: stopped after {MAX_PAGES} pages with more threads left; resume with --cursor {cursor}", file=sys.stderr)
            break
    print(json.dumps({"pageInfo": {"hasNextPage": more, "endCursor": cursor}, "threads": merged, **tally(merged)}, indent=2))
    return 0
