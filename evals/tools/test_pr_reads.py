#!/usr/bin/env python3
"""Hermetic checks for the read half of `crew-pr-actions.py`: fields, absence, failure, threads.

Every case runs the real CLI as a subprocess with a stub `gh` first on PATH, so the tool's own
behavior towards the outside world is what is measured. The four properties are the contract a
prompt depends on: a field list prints bare lines in the order asked, a field gh did not return
prints empty with exit 0, a failed call exits nonzero carrying gh's message, and `diff` passes the
patch through byte for byte.

The fetch cases cover the flat thread shape, because the raw GraphQL envelope made every caller
know `data.repository.pullRequest.reviewThreads` and a caller that guessed wrong got
`Cannot iterate over null`. Counts are taken over the merged set, and a failed fetch prints no JSON
at all, so "no threads" and "could not read" stay distinguishable.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "review" / "crew-pr-actions.py"

PATCH = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-one\n+two\n"
VIEW = {"number": 42, "title": "Wrap the reads", "headRefName": "refactor/gh-reads",
        "files": [{"path": "b.py"}, {"path": "a.py"}]}

THREAD = {"id": "T_1", "isResolved": False, "isOutdated": False,
          "comments": {"nodes": [{"databaseId": 9, "body": "why?"}]}}


def stub_gh(directory, body, code=0, stderr=""):
    """A `gh` that records its argv and prints `body`; `code` and `stderr` simulate a failure."""
    return stub_pages(directory, {"": (body, code, stderr)})


def stub_pages(directory, pages):
    """A `gh` whose answer depends on the `cursor=` it was handed, so pagination is observable.

    `pages` maps a cursor to `(body, code, stderr)`; the empty-string key answers a call that asked
    for no cursor. A cursor the map does not hold exits 1, which is how a wrong argv surfaces.
    """
    log = directory / "gh.calls"
    config = directory / "gh.pages.json"
    config.write_text(json.dumps(pages))
    script = directory / "gh"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        f'{sys.executable} "{directory / "gh_stub.py"}" "$@"\n'
    )
    (directory / "gh_stub.py").write_text(
        "import json, sys\n"
        f"pages = json.loads(open({str(config)!r}).read())\n"
        "cursor = ''\n"
        "for index, item in enumerate(sys.argv[1:]):\n"
        "    if item.startswith('cursor='):\n"
        "        cursor = item.split('=', 1)[1]\n"
        "answer = pages.get(cursor)\n"
        "if answer is None:\n"
        "    print(f'gh stub: no page for cursor {cursor!r}', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "body, code, stderr = answer\n"
        "sys.stderr.write(stderr + ('\\n' if stderr else ''))\n"
        "sys.stdout.write(body)\n"
        "sys.exit(code)\n"
    )
    script.chmod(0o755)
    return log


def run(arguments, bindir, home):
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
           "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(home)}
    return subprocess.run([sys.executable, str(TOOL), *arguments],
                          capture_output=True, text=True, env=env)


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"pass: {name}")


def envelope(nodes, has_next=False, cursor=None, extra=None):
    """gh's real GraphQL answer, nested where the callers used to have to know the path."""
    page = {"reviewThreads": {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                              "nodes": nodes}}
    return json.dumps({**(extra or {}), "data": {"repository": {"pullRequest": page}}})


class Sandbox:
    """A scratch HOME with a stub `gh`; each case installs the body it needs."""

    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)
        self.bindir = self.path / "bin"
        self.bindir.mkdir()
        asset = self.path / ".agent" / "bin" / "pr-review-threads.graphql"
        asset.parent.mkdir(parents=True)
        asset.write_text((ROOT / ".agent" / "tools" / "review" /
                          "pr-review-threads.graphql").read_text())
        return self

    def __exit__(self, *_):
        self.temporary.cleanup()

    def stub(self, body, code=0, stderr=""):
        log = self.bindir / "gh.calls"
        if log.exists():
            log.unlink()
        self.log = stub_gh(self.bindir, body, code, stderr)
        return self

    def stub_pages(self, pages):
        log = self.bindir / "gh.calls"
        if log.exists():
            log.unlink()
        self.log = stub_pages(self.bindir, pages)
        return self

    def run(self, *arguments):
        return run(arguments, self.bindir, self.path)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


def field_cases(box):
    """Three fields, in the order asked, one bare line each — the resolver's one-call saving."""
    box.stub(json.dumps(VIEW))
    result = box.run("view", "--pr", "42", "--repo", "owner/repo",
                     "--field", "branch,title,files")
    check("view --field exits 0", result.returncode == 0, result.stderr)
    check("view --field prints one line per field in the order asked",
          result.stdout.splitlines()[:3] == ["refactor/gh-reads", "Wrap the reads", "b.py a.py"],
          result.stdout)
    called = box.calls()[0]
    check("branch is asked for as headRefName", "headRefName" in called, called)
    check("the repo and PR reach gh", "--repo owner/repo" in called and " 42" in called, called)


def absent_field_cases(box):
    """A field gh did not return prints empty and still exits 0, so a caller can test it."""
    box.stub(json.dumps({"title": "only a title"}))
    result = box.run("view", "--pr", "42", "--field", "branch,title")
    check("a missing field exits 0", result.returncode == 0, result.stderr)
    check("a missing field prints an empty line",
          result.stdout.splitlines() == ["", "only a title"], result.stdout)


def failing_gh_cases(box):
    """A failed call is loud: nonzero exit and gh's own message, never an empty answer."""
    box.stub("{}", code=1, stderr="HTTP 404: Not Found (https://api.github.com)")
    result = box.run("view", "--pr", "999", "--field", "title")
    check("a failing gh exits nonzero", result.returncode != 0, result.stdout)
    check("a failing gh carries its own message", "HTTP 404" in result.stderr, result.stderr)
    check("a failing gh prints no field line", result.stdout.strip() == "", result.stdout)


def diff_cases(box):
    """`diff` writes the patch to stdout unchanged, so a caller redirects it to a file."""
    box.stub(PATCH)
    result = box.run("diff", "--pr", "42", "--repo", "owner/repo")
    check("diff exits 0", result.returncode == 0, result.stderr)
    check("diff is byte-for-byte", result.stdout == PATCH, repr(result.stdout))
    check("diff names the PR", "pr diff 42" in box.calls()[0], box.calls())


def other_read_cases(box):
    """`repo` and `issue` answer the two fields the prompts asked gh for directly."""
    box.stub(json.dumps({"nameWithOwner": "elastic/el-capitan"}))
    result = box.run("repo", "--field", "nameWithOwner")
    check("repo --field nameWithOwner", result.stdout.strip() == "elastic/el-capitan", result.stdout)
    check("repo view asks for the field", "repo view" in box.calls()[0], box.calls())

    box.stub(json.dumps({"title": "A defect", "body": "Steps:\n1. run it"}))
    result = box.run("issue", "--number", "7", "--repo", "owner/repo", "--field", "title,body")
    check("issue --field exits 0", result.returncode == 0, result.stderr)
    lines = result.stdout.splitlines()
    check("issue prints the title then the body", lines[0] == "A defect" and "Steps:" in lines[1],
          lines)
    check("a multiline body stays one line", len(lines) == 2, lines)


def fetch_shape_cases(box):
    """The flat shape: pageInfo and threads at the top level, counts over the whole set."""
    threads = [THREAD,
               {"id": "T_2", "isResolved": True, "isOutdated": False, "comments": {"nodes": []}},
               {"id": "T_3", "isResolved": False, "isOutdated": True, "comments": {"nodes": []}}]
    box.stub(envelope(threads, has_next=False, cursor="CUR"))
    result = box.run("fetch", "--repo", "owner/repo", "--pr", "42")
    check("fetch exits 0", result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    check("fetch has no raw envelope", "data" not in payload, list(payload))
    check("fetch exposes pageInfo at the top", payload["pageInfo"] == {"hasNextPage": False,
                                                                      "endCursor": "CUR"})
    check("fetch exposes threads at the top", [t["id"] for t in payload["threads"]] ==
          ["T_1", "T_2", "T_3"], payload["threads"])
    check("a thread keeps its GraphQL node shape", payload["threads"][0] == threads[0],
          payload["threads"][0])
    check("the counts cover mixed resolved and outdated threads",
          (payload["resolved"], payload["unresolvedCurrent"], payload["unresolvedOutdated"])
          == (1, 1, 1), payload)


def fetch_merge_cases(box):
    """With --cursor the pages accumulate and the counts are over the merged set, not per page."""
    box.stub_pages({
        "PAGE1": (envelope([THREAD], has_next=True, cursor="PAGE2"), 0, ""),
        "PAGE2": (envelope([{"id": "T_2", "isResolved": True, "isOutdated": False},
                            {"id": "T_3", "isResolved": False, "isOutdated": True}],
                           has_next=False, cursor="PAGE2"), 0, ""),
    })
    result = box.run("fetch", "--repo", "owner/repo", "--pr", "42", "--cursor", "PAGE1")
    check("a multi-page fetch exits 0", result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    check("threads accumulate across pages", [t["id"] for t in payload["threads"]] ==
          ["T_1", "T_2", "T_3"], payload["threads"])
    check("counts are merged, not per page",
          (payload["resolved"], payload["unresolvedCurrent"], payload["unresolvedOutdated"])
          == (1, 1, 1), payload)
    check("the loop ends on hasNextPage false", payload["pageInfo"]["hasNextPage"] is False,
          payload["pageInfo"])
    calls = box.calls()
    check("the first request carries the caller's cursor", "cursor=PAGE1" in calls[0], calls)
    check("the second request carries the end cursor", "cursor=PAGE2" in calls[1], calls)


def fetch_failure_cases(box):
    """A GraphQL error and a missing pullRequest both exit nonzero, printing no JSON."""
    box.stub(json.dumps({"errors": [{"message": "Could not resolve to a PullRequest"}]}))
    result = box.run("fetch", "--repo", "owner/repo", "--pr", "404")
    check("a GraphQL error exits nonzero", result.returncode != 0, result.stdout)
    check("a GraphQL error prints no JSON", result.stdout.strip() == "", result.stdout)
    check("a GraphQL error names its message",
          "Could not resolve to a PullRequest" in result.stderr, result.stderr)

    box.stub(json.dumps({"data": {"repository": {"pullRequest": None}}}))
    result = box.run("fetch", "--repo", "owner/repo", "--pr", "404")
    check("a missing pullRequest exits nonzero", result.returncode != 0, result.stdout)
    check("a missing pullRequest prints no JSON", result.stdout.strip() == "", result.stdout)

    box.stub("{}", code=1, stderr="HTTP 401: Bad credentials")
    result = box.run("fetch", "--repo", "owner/repo", "--pr", "42")
    check("a failing fetch carries gh's stderr", "Bad credentials" in result.stderr, result.stderr)
    check("a failing fetch prints no JSON", result.stdout.strip() == "", result.stdout)


def fetch_empty_cases(box):
    """A PR nobody has reviewed is a real empty answer: threads [], counts 0, exit 0."""
    box.stub(envelope([], has_next=False, cursor=None))
    result = box.run("fetch", "--repo", "owner/repo", "--pr", "42")
    check("an empty PR exits 0", result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    check("an empty PR prints threads []", payload["threads"] == [], payload)
    check("an empty PR reports zero counts",
          (payload["resolved"], payload["unresolvedCurrent"], payload["unresolvedOutdated"])
          == (0, 0, 0), payload)


def dry_run_cases(box):
    """--dry-run keeps printing the plan and never calls gh."""
    box.stub(envelope([]))
    result = box.run("fetch", "--repo", "owner/repo", "--pr", "42", "--dry-run")
    check("fetch --dry-run exits 0", result.returncode == 0, result.stderr)
    check("fetch --dry-run never calls gh", not box.calls(), box.calls())
    check("fetch --dry-run prints the plan",
          "pr=42" in json.loads(result.stdout)["planned"]["command"])


def main():
    cases = (field_cases, absent_field_cases, failing_gh_cases, diff_cases, other_read_cases,
             fetch_shape_cases, fetch_merge_cases, fetch_failure_cases, fetch_empty_cases,
             dry_run_cases)
    for case in cases:
        with Sandbox() as box:
            case(box)
    print("all crew-pr-actions read checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
