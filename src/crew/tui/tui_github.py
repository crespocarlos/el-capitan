"""The TUI's GitHub facts: every PR and issue the tasks name, read in one `gh api graphql` call and cached on disk.

`fetch` asks for each PR's state, draft, review decision, CI rollup, update and merge times, title and branches, and
each issue's state, then computes LANDED for every merged PR (`ls_data.verdict`, the rule `crew ls` uses). A failed
read keeps the last good facts, and an item a partial read lost keeps its cached one, with the error. `pr_cell` and `issue_cell` print one
compact cell (`#52 ✓merged landed`, `#56 ●open CI✗`): `…` until the first read, `?` when offline with no cache.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from crew.core.task.ls_data import load_bases, local_remotes, reachable_from, verdict
from crew.core.task.task_progress import GITHUB_PR_URL, ISSUE_URL
from crew.core.task.task_report import number_cell
from crew.lib.files import atomic_write
from crew.lib.git import gh

REFRESH = 360.0  # seconds between reads (6 minutes); `R` reads at once
PR_FIELDS = (
    "number state isDraft reviewDecision updatedAt mergedAt title headRefName baseRefName mergeCommit { oid } "
    "commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }"
)
STATES = {"MERGED": "✓merged", "CLOSED": "✗closed", "OPEN": "●open"}
DRAFT = "◌draft"
ISSUES = {"OPEN": STATES["OPEN"], "CLOSED": "✓closed"}
CI = {"SUCCESS": "CI✓", "FAILURE": "CI✗", "ERROR": "CI✗", "PENDING": "CI…", "EXPECTED": "CI…"}
REVIEW = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes requested"}
LANDED = {"yes": "landed", "no": "not landed", "unknown": "landed?", "not local": "landed? (repo not local)"}
Run = Callable[[str], "tuple[int, str]"]


@dataclass
class Facts:
    """`{url: record}` for PRs and issues, when the last good read was (`fetched_at`), and the last read's error."""

    fetched_at: float | None = None
    prs: dict[str, dict] = field(default_factory=dict)
    issues: dict[str, dict] = field(default_factory=dict)
    error: str = ""


def cache_path() -> Path:
    return Path.home() / ".agent" / "state" / "tui-github.json"


def load_facts(path: Path | None = None) -> Facts:
    try:
        found = json.loads((path or cache_path()).read_text(encoding="utf-8"))
        return Facts(found["fetched_at"], found["prs"], found["issues"])
    except (OSError, ValueError, KeyError, TypeError):
        return Facts()


def save_facts(facts: Facts, path: Path | None = None) -> None:
    with contextlib.suppress(OSError):  # the next read writes it again
        atomic_write(path or cache_path(), json.dumps(asdict(facts)))


def query(urls: list[str]) -> tuple[str, dict[tuple[str, str], str]]:
    """One GraphQL query for every PR and issue URL, grouped by repository; with `{(repo alias, item alias): url}`."""
    repos: dict[str, list[tuple[str, str, str]]] = {}
    for url in dict.fromkeys(urls):
        found = GITHUB_PR_URL.fullmatch(url) or ISSUE_URL.fullmatch(url)
        if found:
            kind = "pullRequest" if "/pull/" in url else "issue"
            repos.setdefault(found.group(1), []).append((kind, found.group(2), url))
    parts, aliases = [], {}
    for index, (repo, items) in enumerate(sorted(repos.items())):
        owner, name = repo.split("/")
        fields = []
        for kind, number, url in items:
            alias = f"{kind[0]}{number}"
            aliases[(f"r{index}", alias)] = url
            fields.append(f"{alias}: {kind}(number: {number}) {{ {PR_FIELDS if kind == 'pullRequest' else 'state title updatedAt'} }}")
        parts.append(f"r{index}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ defaultBranchRef {{ name }} {' '.join(fields)} }}")
    return "query { " + " ".join(parts) + " }", aliases


def run_gh(text: str) -> tuple[int, str]:
    """`gh api graphql` with the query; stdout (the JSON, partial data included) or stderr on failure."""
    try:
        done = gh("api", "graphql", "-f", f"query={text}", timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        return 1, str(error)
    return done.returncode, done.stdout or done.stderr


def landed(record: dict, url: str, default: str, clone: Path | None) -> str:
    """`yes`, `no`, `unknown` or `not local` for a merged PR: merged into the default branch (or the PR's base when
    GitHub names none) is `yes`; another base asks the repository's own `clone` for its remotes and `landing_bases`,
    as `crew ls` does, and with no clone on this machine it is `not local`."""
    default = default or record["base"]
    if record["base"] == default:
        return "yes"
    if clone is None:
        return "not local"
    remote = local_remotes(clone).get("/".join(url.split("/")[3:5]).lower())
    found = {"number": record["number"], "state": record["state"], "base": record["base"], "default": default, "merge_commit": record.get("merge_commit")}
    return verdict(found, lambda sha, ref: reachable_from(sha, ref, clone), load_bases(clone) if remote else [], remote)


def fetch(urls: list[str], before: Facts, run: Run = run_gh, now: float | None = None, clones: dict[str, Path] | None = None) -> Facts:
    """The facts of `urls` from one call, LANDED computed for each merged PR in its repository's clone (`clones`,
    `{owner/repo: path}`); an item the read did not return keeps its cached fact, and the error (GraphQL's first, or
    the exit code) is kept; with no data at all, `before` with the error."""
    text, aliases = query(urls)
    if not aliases:
        return Facts(time.time() if now is None else now)
    code, out = run(text)
    try:
        payload = json.loads(out)
        data = payload.get("data") or {}
    except (ValueError, AttributeError):
        payload, data = {}, {}
    errors = payload.get("errors") or [{}]
    error = errors[0].get("message") or ((out.strip().splitlines() or [f"gh exit {code}"])[-1] if code else "")
    if not data:
        return Facts(before.fetched_at, before.prs, before.issues, error or "no data")
    facts = Facts(time.time() if now is None else now, error=error)
    for (repo_alias, alias), url in aliases.items():
        repo = data.get(repo_alias) or {}
        item, issue = repo.get(alias), alias.startswith("i")
        if not item:
            cached = before.issues if issue else before.prs
            (facts.issues if issue else facts.prs).update({url: cached[url]} if url in cached else {})
            continue
        if issue:
            facts.issues[url] = {"state": item["state"], "title": item.get("title", ""), "updated": item.get("updatedAt", "")}
            continue
        rollup = ((item.get("commits") or {}).get("nodes") or [{}])[0].get("commit", {}).get("statusCheckRollup") or {}
        record = {
            "number": item["number"],
            "state": item["state"],
            "draft": bool(item.get("isDraft")),
            "review": item.get("reviewDecision") or "",
            "ci": rollup.get("state", ""),
            "updated": item.get("updatedAt", ""),
            "merged": item.get("mergedAt") or "",
            "title": item.get("title", ""),
            "head": item.get("headRefName", ""),
            "base": item.get("baseRefName", ""),
            "merge_commit": (item.get("mergeCommit") or {}).get("oid"),
        }
        if record["state"] == "MERGED":
            default = (repo.get("defaultBranchRef") or {}).get("name", "")
            record["landed"] = landed(record, url, default, (clones or {}).get("/".join(url.split("/")[3:5]).lower()))
        facts.prs[url] = record
    return facts


def waiting(facts: Facts) -> str:
    """The mark of a URL with no record: `…` before the first read, `?` offline with no cache or a URL not found."""
    return "…" if facts.fetched_at is None and not facts.error else "?"


def pr_cell(url: str, facts: Facts) -> str:
    """`#52 ✓merged landed`, `#56 ●open CI✗ approved`, `#57 ◌draft`: glyph and word, never colour alone."""
    record = facts.prs.get(url)
    if record is None:
        return f"{number_cell(url)} {waiting(facts)}"
    state = DRAFT if record["state"] == "OPEN" and record["draft"] else STATES.get(record["state"], record["state"].lower())
    extra = [LANDED.get(record.get("landed", ""), "")] if record["state"] == "MERGED" else [CI.get(record["ci"], ""), REVIEW.get(record["review"], "")]
    return " ".join([number_cell(url), state, *filter(None, extra)])


def issue_cell(url: str, facts: Facts) -> str:
    if not url:
        return "-"
    record = facts.issues.get(url)
    return f"{number_cell(url)} {waiting(facts) if record is None else ISSUES.get(record['state'], ISSUES['CLOSED'])}"
