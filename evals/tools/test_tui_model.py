#!/usr/bin/env python3
"""The crew TUI (`crew.tui`): its view model over seeded task directories, the GitHub facts from one stubbed
`gh` call, the runs ledger, `--once` without Textual, pilot tests and per-tab snapshots (Textual and the snapshot
plugin come with the `tui` dependency group), and one status move run for real against a temp task.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from task_fixture import record_status

from crew.lib.runs import append_run, open_run, read_runs
from crew.task import crew_task
from crew.task.task_gc import old_lines
from crew.task.task_progress import append_metric
from crew.tui import tui_model, tui_views
from crew.tui.tui_github import Facts, fetch, landed, pr_cell, query
from crew.tui.tui_model import Caches, Filters, collect, live_tick, parse_filter
from crew.tui.tui_moves import CREW_TASK, SHIPPED_NOTE, STALE_NOTE, moves
from crew.tui.tui_views import expanded

if TYPE_CHECKING:
    from textual.app import App
    from textual.pilot import Pilot

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

NOW = time.time()
HOUR = 3600


def stamp(hours_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - hours_ago * HOUR))


ISSUE = "https://github.com/acme/widgets/issues/12"
PR = "https://github.com/acme/widgets/pull/{}"


def agent_end(agent_id: str, new: int, cache_read: int) -> str:
    """An `agent_end` METRIC whose new tokens (input + output + cache_write) total `new`."""
    return (f"METRIC: agent_end agent=crew-builder agent_id={agent_id} tokens=99000 input=10 output=990 "
            f"cache_read={cache_read} cache_write={new - 1000}")


def seed(home: Path) -> Path:
    """Tasks: running with an issue and a PR, blocked with a dead stage, stale under a live lock, done with two PRs;
    worktrees: fresh, stale, malformed, no lock. Tokens: 259k from an agent, `-`, ~259k reported, 1.1M from agents."""
    tasks = home / ".agent" / "tasks"
    specs = (
        ("T1", "running", "IMPLEMENTING", "acme/widgets", f"Issue: {ISSUE}\n\n- [x] a\n- [ ] b\n",
         [(5, "METRIC: stage_start stage=review"), (4.5, agent_end("a1", 259_000, 401_000)),
          (4, "METRIC: stage_end stage=review"),
          (2, "METRIC: stage_start stage=implement workers=2"), (2, f"PR: {PR.format(9)}")]),
        ("T2", "blocked", "APPROVED", "acme/gadgets", "## Branch: feat/gadgets\n\n",
         [(8, "METRIC: stage_start stage=review"), (1, "BLOCKED: waiting for keys")]),
        ("T3", "idle", "IMPLEMENTING", "acme/widgets", "",
         [(20 * 24 + 1, "METRIC: stage_end stage=implement workers=1 tokens_reported=259000"),
          (20 * 24, "TRANSITION: APPROVED → IMPLEMENTING")]),
        ("T4", "shipped", "DONE", "acme/widgets", "",
         [(50, "METRIC: stage_start stage=review"), (49.5, agent_end("a4", 600_000, 1000)),
          (49.4, agent_end("a5", 500_000, 2000)), (49, f"PR opened: {PR.format(7)}"), (49, f"PR: {PR.format(8)}")]),
    )
    for uuid, slug, status, repo, body, progress in specs:
        task = tasks / uuid
        task.mkdir(parents=True)
        (task / "SPEC.md").write_text(f"# {slug}\n\n## Status\n{status}\n\n{body}")
        (task / ".task-id").write_text(json.dumps({"slug": slug, "repo_remote_url": f"git@github.com:{repo}.git"}))
        (task / "PROGRESS.md").write_text("".join(f"[{stamp(h)}] {line}\n" for h, line in progress))
        record_status(task, status)
        old = NOW - max(h for h, _ in progress) * HOUR
        for path in task.iterdir():
            os.utime(path, (old, old))
    locks = (("fresh", f"task=T3\nstarted={int(NOW - 600)}\n"), ("old", f"task=T9\nstarted={int(NOW - 7 * HOUR)}\n"),
             ("broken", "task=T1\nstarted=soon\n"), ("bare", None))
    for tree, text in locks:
        (home / tree).mkdir()
        if text:
            (home / tree / ".crew-worker.lock").write_text(text)
    return tasks


@pytest.fixture
def home(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp))
    monkeypatch.delenv("CREW_MEMORY_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)  # no transcript outside the temp home is read
    monkeypatch.chdir(tmp)
    seed(tmp)
    return tmp


def views(home: Path, filters: Filters, facts: Facts | None = None) -> dict:
    trees = [home / name for name in ("fresh", "old", "broken", "bare")]
    return collect(home / ".agent" / "tasks", filters, facts, trees=trees, here=lambda: {}, now=NOW)[0]


def pr_item(number: int, state: str, head: str, ci: str = "SUCCESS", review: str | None = None) -> dict:
    """A PR as the GraphQL query returns it, into `main`."""
    return {"number": number, "state": state, "isDraft": False, "reviewDecision": review, "updatedAt": "2026-11-27T10:00:00Z",
            "mergedAt": "2026-11-27T10:00:00Z" if state == "MERGED" else None, "title": f"change {number}", "headRefName": head,
            "baseRefName": "main", "mergeCommit": {"oid": "abc"} if state == "MERGED" else None,
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci}}}]}}


SEEDED = {ISSUE: {"state": "OPEN", "title": "widgets break"}, PR.format(9): pr_item(9, "OPEN", "feat/run", "FAILURE", "APPROVED"),
          PR.format(7): pr_item(7, "MERGED", "fix/a"), PR.format(8): pr_item(8, "MERGED", "fix/b")}


def github(items: dict[str, dict], calls: list[str]) -> Callable[[str], tuple[int, str]]:
    """A stub for `gh api graphql`: answers the query for `items`' URLs with them, each repository's default `main`."""
    def run(text: str) -> tuple[int, str]:
        calls.append(text)
        data: dict = {}
        for (repo, alias), url in query(list(items))[1].items():
            data.setdefault(repo, {"defaultBranchRef": {"name": "main"}})[alias] = items[url]
        return 0, json.dumps({"data": data})
    return run


def facts_of(items: dict[str, dict]) -> Facts:
    return fetch(list(items), Facts(), github(items, []), now=NOW)


@pytest.mark.parametrize("config,filters,slugs", [
    (None, Filters(), ["blocked", "running", "idle"]),  # BLOCKED needs you: pinned first
    (None, Filters(repo="widgets"), ["running", "idle"]),
    ("acme/gadgets", Filters(), ["blocked"]),  # ls.repo is the scope when no repo is given
    ("acme/gadgets", Filters(repo="all"), ["blocked", "running", "idle"]),  # --repo wins
    ("acme/gadgets", Filters(repo="here"), ["blocked", "running", "idle"]),  # here: the cwd's, none outside a repo
    (None, Filters(text=("idle",)), ["idle"]),  # a filter word
])
def test_ongoing_order_and_scope(home: Path, config: str | None, filters: Filters, slugs: list[str]) -> None:
    """Ongoing never shows DONE; the summary shows every task, DONE included, newest first."""
    if config:
        (home / ".agent" / "config.json").write_text(json.dumps({"ls": {"repo": config}}))
    found = views(home, filters)
    assert [row[1] for row in found["ongoing"].rows] == slugs
    assert found["ongoing"].rows[0][0] == ("! APPROVED" if slugs[0] == "blocked" else "IMPLEMENTING")
    newest = [slug for slug in ("blocked", "running", "shipped", "idle") if slug in slugs or (slug == "shipped" and "running" in slugs)]
    assert [row[0] for row in found["summary"].rows] == newest


@pytest.mark.parametrize("slug,cells,links", [
    ("running", ("#12 ●open", "#9 ●open CI✗ approved", "1/2", "running implement", "-", "259k", ""), {"ISSUE": ISSUE, "PR": PR.format(9)}),
    ("blocked", ("-", "-", "-", "stuck review", "-", "-", "BLOCKED: waiting for keys"), {}),
    ("idle", ("-", "-", "-", "running implement", "-", "~259k", "stale"), {}),
])
def test_ongoing_cells(home: Path, slug: str, cells: tuple, links: dict) -> None:
    """ISSUE and PR with their GitHub state, PROGRESS, ACTIVITY (an open stage, a live lock, a stage past 6 h), LIVE,
    TOKENS (agents' new tokens, none, a `tokens_reported` as `~`), NOTE."""
    view = views(home, Filters(), facts_of(SEEDED))["ongoing"]
    index = [row[1] for row in view.rows].index(slug)
    assert view.header[3:] == ("ISSUE", "PR", "PROGRESS", "ACTIVITY", "LIVE", "TOKENS", "NOTE")
    assert (view.rows[index][3:], view.links[index]) == (cells, links)


def test_summary_rows_and_pr_children(home: Path) -> None:
    """One row per task, newest first, one compact cell per PR (newest first); several PRs expand into child rows,
    each selectable with its own PR link; before the first GitHub read every cell waits with `…`."""
    view = views(home, Filters(), facts_of(SEEDED))["summary"]
    shipped = [row[0] for row in view.rows].index("shipped")
    assert view.rows[shipped][2:] == ("DONE", "-", "#8 ✓merged landed  #7 ✓merged landed")
    opened = expanded(view, {view.keys[shipped]})
    assert opened.rows[shipped][0] == "▾ shipped" and opened.rows[shipped + 1:shipped + 3] == [
        ("  └ change 8", "fix/b", "", "", "#8 ✓merged landed"), ("  └ change 7", "fix/a", "", "", "#7 ✓merged landed")]
    assert opened.links[shipped + 1] == {"PR": PR.format(8)} and opened.moves[shipped + 1] == []
    assert views(home, Filters())["summary"].rows[shipped][4] == "#8 …  #7 …"


PROGRAM = """# program

## Status
IMPLEMENTING

## Acceptance criteria
### Phase 1: hotfixes (`fix/one`)
- [x] a
- [x] b

### Phase 2: views (`feat/two`)
- [x] c
- [ ] d

### Phase 3: later `x` work (`feat/three`)
- [ ] e

## Tasks
- [ ] T1
"""


def test_phases_map_to_prs_by_branch(home: Path) -> None:
    """A spec's `### Phase …` headings with a branch in backticks: each phase's PR is the task's PR whose head is that
    branch, its criteria counted in its section; the task row shows the phase in progress."""
    task = home / ".agent" / "tasks" / "T6"
    task.mkdir()
    (task / "SPEC.md").write_text(PROGRAM)
    (task / ".task-id").write_text(json.dumps({"slug": "program", "repo_remote_url": "git@github.com:acme/widgets.git"}))
    (task / "PROGRESS.md").write_text(f"[{stamp(1)}] PR: {PR.format(20)}\n[{stamp(1)}] PR: {PR.format(21)}\n")
    record_status(task, "IMPLEMENTING")
    items = {**SEEDED, PR.format(20): pr_item(20, "MERGED", "fix/one"), PR.format(21): pr_item(21, "OPEN", "feat/two", "PENDING")}
    view = views(home, Filters(), facts_of(items))["ongoing"]
    row = [r[1] for r in view.rows].index("program")
    assert view.rows[row][4] == "phase 2/3"
    assert [(c.cells[1], c.cells[2], c.cells[4], c.cells[5], c.url) for c in view.children[view.keys[row]]] == [
        ("  └ Phase 1: hotfixes", "fix/one", "#20 ✓merged landed", "2/2", PR.format(20)),
        ("  └ Phase 2: views", "feat/two", "#21 ●open CI…", "1/2", PR.format(21)),
        ("  └ Phase 3: later `x` work", "feat/three", "-", "0/1", "")]
    assert "  └ Phase 3: later `x` work" in "\n".join(tui_model.render(view)), "the branch is the last backtick span"


def test_github_facts_one_batched_call_partial_and_offline(home: Path) -> None:
    """N PRs and an issue across two repositories are one `gh` call. A partial read (one repository null, GraphQL's
    error, exit 1) keeps that repository's cached facts and shows the error; a failed read keeps every fact; with no
    facts the cells show `…` before the first read and `?` offline."""
    other = "https://github.com/acme/gadgets/pull/3"
    items = {**SEEDED, other: pr_item(3, "OPEN", "x")}
    calls: list[str] = []
    facts = fetch(list(items), Facts(), github(items, calls), now=NOW)
    assert len(calls) == 1 and calls[0].count("repository(") == 2 and calls[0].count("pullRequest(") == 4
    answer = json.loads(github(items, [])(calls[0])[1])
    answer["data"]["r0"], answer["errors"] = None, [{"message": "Could not resolve to a Repository"}]
    partial = fetch(list(items), facts, lambda text: (1, json.dumps(answer)), now=NOW + 60)
    assert partial.prs == facts.prs and (partial.fetched_at, partial.error) == (NOW + 60, "Could not resolve to a Repository")
    assert tui_model.freshness(partial, NOW + 60) == "GitHub 0m ago (Could not resolve to a Repository)"
    offline = fetch(list(items), facts, lambda text: (1, "error connecting to api.github.com"))
    assert (offline.prs, offline.fetched_at, offline.error) == (facts.prs, NOW, "error connecting to api.github.com")
    assert tui_model.freshness(offline, NOW + 7200) == "GitHub 2h ago (error connecting to api.github.com)"
    assert [pr_cell(other, f) for f in (Facts(), Facts(error="offline"))] == ["#3 …", "#3 ?"]


def test_landed_reads_each_repository_clone(home: Path) -> None:
    """Launched from a third directory, a PR merged into a landing base is landed when its own repository's clone
    names that base, and `landed? (repo not local)` with no clone; an empty defaultBranchRef takes the base."""
    clones = {}
    for name in ("widgets", "gadgets"):
        repo = home / "clones" / name
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", f"git@github.com:acme/{name}.git"], check=True)
        (repo / "AGENTS.md").write_text("landing_bases: release\n")
        clones[f"acme/{name}"] = repo
    items = {f"https://github.com/acme/{name}/pull/1": {**pr_item(1, "MERGED", "x"), "baseRefName": "release"} for name in ("widgets", "gadgets", "other")}
    facts = fetch(list(items), Facts(), github(items, []), now=NOW, clones=clones)
    assert [pr_cell(url, facts) for url in items] == ["#1 ✓merged landed", "#1 ✓merged landed", "#1 ✓merged landed? (repo not local)"]
    assert landed({"number": 1, "state": "MERGED", "base": "release"}, PR.format(1), "", None) == "yes"


def test_runs_ledger_shows_standalone_runs_and_gc_prunes_it(runs_ledger: Path) -> None:
    """Standalone runs show in Runs, newest first, a review inside a task does not; two resolves of one PR are two
    rows, the end line finding its own run; a run with no end past 6 h says so; gc prunes lines by their stamp."""
    resolve = "resolve acme/widgets#6"
    append_run("/r/crew-review-w/review/1", "start", kind="review", mode="pr", target="acme/widgets#5", task="")
    append_run("/t/T1/review/2", "start", kind="review", mode="self", target="widgets", task="/t/T1")
    append_run(f"{resolve}@2026-11-27T00:00:00Z", "start", kind="resolve", target="acme/widgets#6")
    append_run(open_run(resolve), "end", outcome="done")
    append_run(f"{resolve}@2026-11-28T00:00:00Z", "start", kind="resolve", target="acme/widgets#6")
    lines = [json.loads(line) for line in runs_ledger.read_text().splitlines()]
    lines[0]["at"] = stamp(8)
    runs_ledger.write_text("".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines))
    view = tui_views.runs_view([], tui_views.Snapshot({}, [], NOW, runs=read_runs()))
    assert [row[:3] for row in view.rows] == [("resolve pr", "acme/widgets#6", "running"), ("resolve pr", "acme/widgets#6", "done"),
                                              ("review pr", "acme/widgets#5", "no end recorded")]
    assert view.links[2] == {"PR": "https://github.com/acme/widgets/pull/5"} and view.count == 3
    kept, dropped = old_lines(runs_ledger, NOW - 7 * HOUR)
    assert len(dropped) == 1 and len(kept) == 4


CALL = {"input_tokens": 1000, "output_tokens": 1000, "cache_read_input_tokens": 50000, "cache_creation_input_tokens": 0}


def iso(minutes_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW - minutes_ago * 60))


def transcript(home: Path, agent_id: str, task: str, calls: int, minutes_ago: float = 1, session: str = "s1",
               said_minutes_ago: float | None = None) -> Path:
    """A subagent transcript under the temp `~/.claude`: the dispatch prompt naming `task`, then `calls` assistant
    calls of 2k new tokens each (the first repeated, as one message per content block is), stamped
    `said_minutes_ago` (default: when the file was last modified)."""
    folder = home / ".claude" / "projects" / "-repo" / session / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    text = {"type": "text", "text": f"crew-task: {task}\nGo."}
    prompt = {"type": "user", "message": {"role": "user", "content": [text]}}
    said = iso(minutes_ago if said_minutes_ago is None else said_minutes_ago)
    calls_made = [1, *range(1, calls + 1)]
    turns = [prompt] + [{"type": "assistant", "timestamp": said, "message": {"id": f"m{n}", "usage": CALL}}
                        for n in calls_made]
    path = folder / f"agent-{agent_id}.jsonl"
    path.write_text("".join(json.dumps(turn) + "\n" for turn in turns))
    os.utime(path, (NOW - minutes_ago * 60,) * 2)
    return path


def test_live_tokens_of_running_agents(home: Path) -> None:
    """One running agent shows in LIVE and the workers view; two add up; TOKENS and the total never change."""
    tasks = home / ".agent" / "tasks"
    transcript(home, "b1", str(tasks / "T1"), 46)
    before = views(home, Filters())
    running = before["ongoing"].rows[1]
    assert running[1] == "running" and running[6:9] == ("running implement", "92k", "259k"), running
    assert ("agent", "running", "agent-b1", "1m", "new 92k, cache reads 2.3M") in before["runs"].rows
    transcript(home, "b2", str(tasks / "T1"), 44, session="s2")
    after = views(home, Filters())
    assert after["ongoing"].rows[1][6:9] == ("running implement", "2 · 180k", "259k")
    assert before["ongoing"].notes == after["ongoing"].notes, "live figures never reach the total"


def test_the_fast_tick_reads_appended_lines_and_the_orchestrator_session(home: Path,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """`stage_start` records the orchestrator's session; its own transcript counts from that start, beside the
    subagents', toward the task whose open stage named it last (T3's older one gets nothing). The next fast tick reads
    only the lines appended since and changes the LIVE cell and the total."""
    tasks = home / ".agent" / "tasks"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s9")
    append_metric(home / "bare", "stage_start stage=review")
    assert (home / "bare" / "PROGRESS.md").read_text().endswith("METRIC: stage_start stage=review session=s9\n")
    for task, hours in (("T3", 3), ("T1", 1)):
        progress = tasks / task / "PROGRESS.md"
        progress.write_text(progress.read_text() + f"[{stamp(hours)}] METRIC: stage_start stage=review session=s9\n")
    agent = transcript(home, "b1", str(tasks / "T1"), 3)
    main = home / ".claude" / "projects" / "-repo" / "s9.jsonl"

    def said(path: Path, message: str, minutes_ago: float) -> None:
        line = {"type": "assistant", "timestamp": iso(minutes_ago), "message": {"id": message, "usage": CALL}}
        with path.open("a") as handle:
            handle.write(json.dumps(line) + "\n")

    said(main, "before the stage", 90)
    said(main, "x1", 30)
    found, watch = collect(tasks, Filters(), trees=[], here=lambda: {}, now=NOW)
    assert list(watch.sessions) == [tasks / "T1"] and "session" not in str(found["runs"].rows), "nor in NOTE"
    caches = Caches()
    assert live_tick(watch, caches, [home / ".claude"], NOW) == ({str(tasks / "T1"): "2 · 8k"}, "2 · 8k")
    said(agent, "m9", 0)
    said(main, "x2", 0)
    assert live_tick(watch, caches, [home / ".claude"], NOW)[0] == {str(tasks / "T1"): "2 · 12k"}


@pytest.mark.parametrize("case,minutes_ago,said,shown", [
    ("resumed", 1, 1, True),  # an agent_end 6 minutes ago, a message since
    ("finished", 10, 10, False),  # the agent_end is newer than the transcript
    ("finished, written after its agent_end", 5.9, 6.2, False),  # mtime just after the hook, last message before it
    ("idle", 20, 20, False),  # a transcript quiet for more than 15 minutes
    ("unreadable", 1, 1, False),
])
def test_live_running_agent_rules(home: Path, case: str, minutes_ago: float, said: float, shown: bool) -> None:
    tasks = home / ".agent" / "tasks"
    path = transcript(home, "a1", str(tasks / "T2"), 5, minutes_ago=minutes_ago, said_minutes_ago=said)
    if case.startswith(("resumed", "finished")):
        progress = tasks / "T2" / "PROGRESS.md"
        end = "METRIC: agent_end agent=x agent_id=a1 tokens=1 input=1 output=1 cache_read=1 cache_write=1"
        progress.write_text(progress.read_text() + f"[{stamp(0.1)}] {end}\n")
    if case == "unreadable":
        path.chmod(0)
    try:
        cells = [row for row in views(home, Filters())["ongoing"].rows if row[1] == "blocked"][0][6:8]
    finally:
        path.chmod(0o644)
    assert cells == (("running review", "10k") if shown else ("stuck review", "-")), cells


def test_live_reading_is_bounded_and_cached(home: Path) -> None:
    """A transcript naming another task is read to its first user line and no further. Freshness is the file's own:
    a fresh file in a session whose directories are an hour old is listed (a long-running agent), a file quiet past
    15 minutes is not, and a `subagents` dir unchanged past 6 hours is not listed at all. A config dir reached twice
    (a symlink) counts each transcript once. The cache carries a matching file's offset, so a refresh reads only the
    lines added since, and drops a file once it is quiet past 15 minutes."""
    from crew.task.task_live import running_agents

    tasks = home / ".agent" / "tasks"
    other = transcript(home, "x1", str(home / "elsewhere"), 30, minutes_ago=2)
    quiet = transcript(home, "q1", str(tasks / "T1"), 3, minutes_ago=20)
    long = transcript(home, "l1", str(tasks / "T1"), 3, session="long")
    ancient = transcript(home, "a1", str(tasks / "T1"), 3, session="ancient")
    for path, hours in ((long, 1), (ancient, 7)):
        for folder in (path.parent, path.parent.parent):
            os.utime(folder, (NOW - hours * HOUR,) * 2)
    mine = transcript(home, "m1", str(tasks / "T1"), 3)
    (home / "link").symlink_to(home / ".claude")
    cache: dict = {}
    found = running_agents([tasks / "T1"], [home / ".claude", home / "link"], {}, NOW, cache)
    assert sorted(agent.agent_id for agent in found[tasks / "T1"]) == ["l1", "m1"], found
    key = os.path.realpath
    assert cache[key(other)].offset == len(other.read_bytes().splitlines(keepends=True)[0]), "only the first user line"
    assert key(quiet) not in cache and key(ancient) not in cache
    partial = '{"type": "assi'
    with mine.open("a") as handle:
        handle.write(json.dumps({"type": "assistant", "message": {"id": "m9", "usage": CALL}}) + "\n" + partial)
    os.utime(mine, (NOW - 30,) * 2)
    os.utime(other, (NOW - 20 * 60,) * 2)
    again = running_agents([tasks / "T1"], [home / ".claude"], {}, NOW, cache)
    assert [agent.new for agent in again[tasks / "T1"] if agent.agent_id == "m1"] == [8000]
    assert cache[key(mine)].offset == len(mine.read_bytes()) - len(partial)
    assert key(other) not in cache, "a quiet file leaves the cache, a non-matching one included"


@pytest.mark.parametrize("later,fraction,running", [(0, ".700Z", False), (1, ".000Z", True)])
def test_live_agent_end_in_the_same_second_as_the_last_message(home: Path, later: int, fraction: str,
                                                                running: bool) -> None:
    """`agent_end` is stamped to the second and the transcript to the millisecond: a last message in the very second
    the hook stamped is finished; one in the next second is a resumed agent, running."""
    from crew.task.task_live import running_agents

    tasks = home / ".agent" / "tasks"
    path = transcript(home, "s1", str(tasks / "T1"), 2, minutes_ago=0.5)
    ended = int(NOW - 60)
    said = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ended + later)) + fraction
    path.write_text(path.read_text().replace(iso(0.5), said))
    os.utime(path, (NOW - 30,) * 2)
    found = running_agents([tasks / "T1"], [home / ".claude"], {"s1": float(ended)}, NOW)
    assert bool(found) is running, found


def test_live_config_dirs_count_each_real_dir_once(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`~/.claude`, `$CLAUDE_CONFIG_DIR` (here a symlink to it) and the manifest's `config_dirs` (a `~/` entry
    expanded): each real directory once."""
    (home / ".claude").mkdir()
    (home / "other").mkdir()
    (home / "alias").symlink_to(home / ".claude")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "alias"))
    manifest = {"config_dirs": ["~/other", str(home / ".claude")]}
    (home / ".agent" / "install-manifest.json").write_text(json.dumps(manifest))
    assert tui_model.config_dirs(home) == [home / ".claude", home / "other"]


def test_runs_view_lists_running_stages_and_locks(home: Path) -> None:
    rows = views(home, Filters())["runs"].rows
    assert [row[:3] + row[4:] for row in rows] == [
        ("stage", "running", "implement", "workers=2"),
        ("stage", "blocked", "review", "stale: no stage_end"),
        ("lock", "T9", "~/old", "stale: the guard ignores it"),
        ("lock", "idle", "~/fresh", "live"),
    ]
    hook = (ROOT / ".claude" / "hooks" / "guard" / "shell.sh").read_text()
    assert f"\nSTALE_SECONDS={tui_views.LOCK_STALE_SECONDS}\n" in hook, "the lock threshold follows guard/shell.sh"


def test_locks_come_from_each_task_repository(home: Path) -> None:
    """Run outside any repository, the workers view still reads the lock in a task's recorded checkout."""
    repo = home / "elsewhere"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".crew-worker.lock").write_text(f"task=T1\nstarted={int(NOW - 60)}\n")
    meta = home / ".agent" / "tasks" / "T1" / ".task-id"
    meta.write_text(json.dumps({**json.loads(meta.read_text()), "worktree": str(repo)}))
    found, watch = collect(home / ".agent" / "tasks", Filters(), here=lambda: {}, now=NOW)
    rows = found["runs"].rows
    assert watch.clones == {"acme/widgets": repo}, "a task's recorded worktree is its repository's clone"
    assert [(row[1], Path(row[2].replace("~", str(home))).resolve(), row[4]) for row in rows if row[0] == "lock"] == [
        ("running", repo.resolve(), "live")]


BLOCK, CLOSE = ("blocked", "{t}", "why"), ("mark-done", "{t}", "--force", "--pr-url", STALE_NOTE)
NO_PR = "IMPLEMENTING → DONE [d] Mark done with its PR (unavailable: no PR recorded)"
NOT_CLOSABLE = "ABANDONED → DONE [c] Close as done (--force), with a note (unavailable: crew-task.py does not close ABANDONED)"


@pytest.mark.parametrize("state,prs,expected,unavailable", [
    ("DRAFTING", [], [("mark-approved", "{t}"), BLOCK, CLOSE], []),
    ("APPROVED", [], [("mark-implementing", "{t}", "--branch", "feat/x"), BLOCK, CLOSE], []),
    ("IMPLEMENTING", [PR.format(7), PR.format(8)], [("mark-done", "{t}", "--pr-url", PR.format(8)), BLOCK], []),
    ("IMPLEMENTING", [], [BLOCK, (*CLOSE[:-1], SHIPPED_NOTE)], [NO_PR]),
    ("ON-HOLD", [], [BLOCK, CLOSE], []),
    ("ABANDONED", [], [BLOCK], [NOT_CLOSABLE]),
    ("DONE", [PR.format(8)], [], []),
])
def test_moves_per_state(tmp: Path, state: str, prs: list[str], expected: list[tuple], unavailable: list[str]) -> None:
    """The gate the state allows (mark done with the newest PR), then `blocked` for every task not DONE and close as
    done (`--force`, the note `none (committed to main)` for IMPLEMENTING, else `closed: stale`) for a closable state
    with no PR; a gate not passable yet, and close for ABANDONED, say why. Every move is a subcommand crew-task.py has."""
    found = moves(state, tmp, prs, "feat/x")
    wanted = [[arg.format(t=tmp) for arg in args] for args in expected]
    assert [move.argv(move.default or "why")[3:] for move in found if not move.why] == wanted
    assert [move.title() for move in found if move.why] == unavailable
    choices = crew_task.make_parser()._subparsers._group_actions[0].choices
    assert all(move.args[0] in choices for move in found)


def test_a_move_runs_crew_task_for_real(home: Path) -> None:
    """The app's default runner on a temp task: APPROVED to IMPLEMENTING in SPEC.md through crew-task.py, the spec's
    `## Branch:` recorded and, run outside any checkout of the task, no `worktree`."""
    from crew.tui.tui_widgets import run_command

    task = home / ".agent" / "tasks" / "T2"
    start = moves("APPROVED", task, [], "feat/gadgets")[0]
    code, _, err = run_command(start.argv())
    assert code == 0, err
    meta = json.loads((task / ".task-id").read_text())
    assert "## Status\nIMPLEMENTING" in (task / "SPEC.md").read_text()
    assert meta["branch"] == "feat/gadgets" and "worktree" not in meta, meta


def test_a_tampered_task_offers_only_restore_moves(home: Path) -> None:
    """A Status written outside crew-task shows as TAMPERED in STATE, and the only moves are restore-status and its
    `--accept` with a note; the restore move, run for real, writes the recorded status back."""
    from crew.tui.tui_widgets import run_command

    spec = home / ".agent" / "tasks" / "T2" / "SPEC.md"
    spec.write_text(spec.read_text().replace("## Status\nAPPROVED", "## Status\nIMPLEMENTING"))
    view = views(home, Filters(repo="all"))["ongoing"]
    row = next(i for i, cells in enumerate(view.rows) if cells[1].startswith("blocked"))
    assert view.rows[row][0] == "! TAMPERED (spec says IMPLEMENTING, crew-task recorded APPROVED)", view.rows[row]
    assert [(move.args[0], *move.args[2:], move.ask) for move in view.moves[row]] == [
        ("restore-status", ""), ("restore-status", "--accept", "note")], view.moves[row]
    code, _, err = run_command(view.moves[row][0].argv())
    assert code == 0 and "## Status\nAPPROVED" in spec.read_text(), err


@pytest.mark.parametrize("spec_line", ["", "## Branch: [type/short-description — e.g. feat/x]\n\n"])
def test_no_start_move_without_a_spec_branch(home: Path, spec_line: str) -> None:
    """An APPROVED task whose SPEC.md has no `## Branch:`, or only the template's placeholder, gets its start move
    unavailable, saying to start it from its checkout (only `blocked` and close as done run)."""
    spec = home / ".agent" / "tasks" / "T2" / "SPEC.md"
    spec.write_text(spec.read_text().replace("## Branch: feat/gadgets\n\n", spec_line))
    view = views(home, Filters(repo="all"))["ongoing"]
    row = next(i for i, cells in enumerate(view.rows) if cells[1].startswith("blocked"))
    found = [(move.args[0], *move.args[2:3]) for move in view.moves[row] if not move.why]
    assert found == [("blocked",), ("mark-done", "--force")], view.moves[row]
    assert "from its checkout" in view.moves[row][0].why, view.moves[row]


@pytest.mark.parametrize("text,base,expected", [
    ("repo:acme/w status:implementing status:done Widgets", None, Filters("acme/w", ("IMPLEMENTING", "DONE"), ("widgets",))),
    ("status:approved", Filters("all", ("DONE",), ("x",), 7), Filters("all", ("APPROVED",), (), 7)),
    ("status:bogus", None, ValueError),
    ("colour:red", None, ValueError),
])
def test_parse_filter(text: str, base: Filters | None, expected: object) -> None:
    if expected is ValueError:
        with pytest.raises(ValueError):
            parse_filter(text, base)
    else:
        assert parse_filter(text, base) == expected


@pytest.mark.timeout(300)  # a nested run allowed 60 s
def test_once_prints_every_view_without_textual(home: Path) -> None:
    """`-S` leaves site-packages off the path, so Textual cannot be imported even where it is installed."""
    argv = [sys.executable, "-S", "-m", "crew.tui.crew_tui", "--once", "--repo", "all", "--tasks-dir", str(home / ".agent" / "tasks")]
    done = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, "TERM": "dumb", "PYTHONPATH": str(SRC)}, cwd=home,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    titles = ("1 Ongoing", "2 Tasks · PRs · Issues", "3 Runs", "cost")
    assert all(f"== {name} ==" in done.stdout for name in titles) and "running" in done.stdout
    assert " #12 " in done.stdout and "[link" not in done.stdout, "--once prints the issue as plain text"
    assert " TOKENS " in done.stdout and "tokens: new ~518k, cache reads 401k across 3 tasks shown" in done.stdout


@pytest.mark.timeout(300)  # nested runs, each allowed 60 s
def test_once_fits_120_columns_keeping_the_task_readable(home: Path) -> None:
    """At COLUMNS=120 every table line fits; when NOTE alone can absorb the excess, every TASK is printed in full and
    the cut NOTE ends with `…`; an ON-HOLD task's STATE is `ON-HOLD` and `was APPROVED` starts its NOTE; REPO drops
    the owner every row shares. `fitted` cuts TASK only once NOTE is down to its header's width."""
    from crew.task.task_report import fitted

    tasks = home / ".agent" / "tasks"
    progress = tasks / "T2" / "PROGRESS.md"
    progress.write_text(progress.read_text() + f"[{stamp(0.5)}] BLOCKED: {'waiting for the keys ' * 12}\n")
    held = tasks / "T5"
    held.mkdir()
    (held / "SPEC.md").write_text("# held\n\n## Status\nON-HOLD (auto-hold: idle 15d; was APPROVED)\n")
    (held / ".task-id").write_text(json.dumps({"slug": "tokens-of-running-agents",
                                               "repo_remote_url": "git@github.com:acme/el-capitan.git"}))
    (held / "PROGRESS.md").write_text(f"[{stamp(1)}] TRANSITION: APPROVED → ON-HOLD\n")

    def table(columns: str) -> list[str]:
        argv = [sys.executable, "-m", "crew.tui.crew_tui", "--once", "--repo", "all", "--tasks-dir", str(tasks)]
        done = subprocess.run(argv, capture_output=True, text=True, cwd=home, timeout=60,
                              env={**os.environ, "TERM": "dumb", "COLUMNS": columns})
        assert done.returncode == 0, done.stderr
        return done.stdout.split("\n\n")[0].splitlines()[1:-2]  # the header and the rows, without the note lines

    wide, narrow = table("1000"), table("120")
    note = wide[0].index("NOTE")
    assert max(len(line) for line in wide) - 120 <= max(len(line) for line in wide) - note - len("NOTE"), \
        "the fixture's NOTE alone can absorb the excess"
    assert max(len(line) for line in narrow) <= 120, narrow
    for full, cut in zip(wide[1:], narrow[1:]):
        assert cut[:note].rstrip() == full[:note].rstrip(), "every column before NOTE, TASK included, is untouched"
        assert full[note:].startswith("was APPROVED") == full.startswith("ON-HOLD ") and "(was" not in full
        assert cut == full or cut.endswith("…"), (full, cut)
    assert any(cut.endswith("…") for cut in narrow) and "acme/" not in "\n".join(wide)
    assert any(line.startswith("ON-HOLD ") for line in wide)
    assert fitted([("TASK", "NOTE"), ("abcdefgh", "xxxxxxxx")], 12) == [("TASK", "NOTE"), ("abcde…", "xxx…")]


async def settle(app: App, pilot: Pilot) -> None:
    """Wait until the views are loaded and no read or move is in flight, those they start included (a GitHub read
    starts a local one). It polls the condition rather than awaiting a worker: a newer read cancels an older one."""
    for _ in range(400):
        await pilot.pause(0.05)
        if getattr(app, "views", None) and all(worker.is_finished for worker in app.workers):
            await pilot.pause()
            return


def test_app_rows_keep_their_place_tabs_and_children(home: Path) -> None:
    """Textual is in the `evals/test.sh` environment, so a missing one fails here rather than skipping. One GitHub
    read after the first local read. A refresh that reorders the rows keeps the cursor on its task and updates a
    changed cell in place; `o` and `O` open the selected task's PR and issue; the tabs carry counts and switch with
    1 2 3; `/` filters; in the summary `enter` expands a task into PR rows, `o` on a child opens its PR, `s` there does
    nothing, `←` folds back to the task. Nothing under the tasks dir is written."""
    from crew.tui.tui_app import CrewApp
    from crew.tui.tui_widgets import Lines

    tasks = home / ".agent" / "tasks"
    before = {path: path.stat().st_mtime for path in tasks.rglob("*")}
    opened: list[str] = []
    calls: list[str] = []

    async def drive() -> list:
        app = CrewApp(tasks, Filters(repo="all"), interval=60, gh=github(SEEDED, calls), opener=opened.append, clock=lambda: NOW)
        async with app.run_test(size=(160, 48)) as pilot:
            await settle(app, pilot)
            table = app.query_one("#table")
            assert str(table.get_cell_at((1, 3))) == f"[link={ISSUE}]#12 [#FEA62B]●open[/][/link]", "the issue cell is a terminal link"
            await pilot.press("down", "down")  # T3, the third row
            view = app.views["ongoing"]
            flipped = replace(view, rows=view.rows[::-1], links=view.links[::-1], moves=view.moves[::-1], keys=view.keys[::-1])
            flipped.rows[0] = (*flipped.rows[0][:7], "5k", *flipped.rows[0][8:])
            app.loaded({**app.views, "ongoing": flipped}, app.watched)
            await pilot.pause()
            seen = [([row.key.value for row in table.ordered_rows], table.cursor_row, str(table.get_cell(view.keys[2], "LIVE")))]
            await pilot.press("down", "o", "O")
            labels = [str(tab.label) for tab in app.query("Tab")]
            for keys in (["2"], ["3"], ["c"], ["escape", "1", "slash", *"status:approved", "enter"]):
                await pilot.press(*keys)
                await settle(app, pilot)
                seen.append((app.view_name, table.row_count, isinstance(app.screen, Lines)))
            await pilot.press("escape")  # clears the filter: a reload, awaited before the keys that read its rows
            await settle(app, pilot)
            await pilot.press("2", "down", "down", "enter")
            await settle(app, pilot)
            rows = table.row_count
            await pilot.press("down", "o", "s")
            await pilot.pause()
            child = (app.screen is app.default_screen, app.selected_key())
            await pilot.press("left")
            await pilot.pause()
            folded = (app.selected_key(), table.row_count)
        return [*seen, labels, rows, child, *folded]

    seen = asyncio.run(drive())
    assert seen[0] == ([str(tasks / name) for name in ("T3", "T1", "T2")], 0, "5k"), "the cursor stays on T3, now first"
    assert opened == [PR.format(9), ISSUE, PR.format(8)], "o opens the PR, O the issue; o on a child its own PR"
    assert seen[1:5] == [("summary", 4, False), ("runs", 2, False), ("runs", 2, True), ("ongoing", 1, False)]
    assert seen[5] == ["1 Ongoing (3)", "2 Tasks · PRs · Issues (4)", "3 Runs (2)"]
    assert seen[6:] == [6, (True, f"{tasks / 'T4'}::0"), str(tasks / "T4"), 4], "enter expands, s on a child is nothing, ← folds"
    assert len(calls) == 1, "one GitHub read for every PR and issue"
    assert {path: path.stat().st_mtime for path in tasks.rglob("*")} == before


def test_a_move_runs_in_a_worker_while_input_still_works(home: Path) -> None:
    """`s` on the APPROVED task lists its transitions, the command muted with `~` for home and how to confirm; `esc`
    runs nothing; `enter` runs the move in a worker, the row marked pending and a second `s` refused, and the app still
    switches views while the runner waits; the output goes to the command log (`L`), never the notes. `b` takes its
    reason inline, an empty one refused."""
    from textual.widgets import OptionList

    from crew.tui.tui_app import CrewApp
    from crew.tui.tui_widgets import PENDING, Lines, Status

    tasks = home / ".agent" / "tasks"
    gate, ran = threading.Event(), []

    def runner(argv: list[str]) -> tuple[int, str, str]:
        ran.append(argv)
        gate.wait(10)
        return 1, "", "error: blocked is APPROVED, not DRAFTING; nothing written"

    async def drive() -> list:
        app = CrewApp(tasks, Filters(repo="all"), interval=60, gh=github(SEEDED, []), runner=runner)
        async with app.run_test() as pilot:
            await settle(app, pilot)
            await pilot.press("s")
            seen = [str(app.screen.query_one(OptionList).get_option_at_index(0).prompt),
                    str(app.screen.query_one("#command").render())]
            await pilot.press("escape")
            seen.append(list(ran))
            await pilot.press("s", "enter")
            await pilot.pause()
            seen.append(str(app.query_one("#table").get_row(str(tasks / "T2"))[0]))
            await pilot.press("s", "3")  # refused while the move runs; the view still switches
            seen.append((isinstance(app.screen, Status), app.view_name))
            await pilot.press("1")
            gate.set()
            await settle(app, pilot)
            seen.append((app.pending, str(app.query_one("#notes").render())))
            await pilot.press("L")
            seen.append(isinstance(app.screen, Lines))
            await pilot.press("escape", "s", "b", "enter", *"no keys", "enter")
            await settle(app, pilot)
        return [*seen, app.command_log]

    option, command, cancelled, state, (again, view), (pending, notes), logged, lines = asyncio.run(drive())
    assert option == "APPROVED → IMPLEMENTING [i] Start on feat/gadgets"
    assert "mark-implementing ~/.agent/tasks/T2 --branch feat/gadgets\nenter runs this · esc cancels" in command, command
    assert cancelled == [] and state == f"{PENDING}[#FEA62B]! [/]APPROVED" and (again, view) == (False, "runs")
    assert pending == set() and "exit" not in notes and logged
    start = [*CREW_TASK, "mark-implementing", str(tasks / "T2"), "--branch", "feat/gadgets"]
    assert ran == [start, [*CREW_TASK, "blocked", str(tasks / "T2"), "no keys"]]
    assert "error: blocked is APPROVED, not DRAFTING; nothing written" in lines and lines.count("exit 1") == 2, lines


@pytest.mark.parametrize("size", [(80, 24), (160, 48)])
@pytest.mark.parametrize("tab", ["1", "2", "3"])
def test_snapshot_per_tab(home: Path, snap_compare: Callable[..., bool], tab: str, size: tuple[int, int]) -> None:
    """Each tab at 80×24 and 160×48 (the detail pane shows only at 100 columns or more), GitHub facts from the stub."""
    from crew.tui.tui_app import CrewApp

    async def ready(pilot: Pilot) -> None:
        await settle(pilot.app, pilot)
        await pilot.press(tab)
        await settle(pilot.app, pilot)

    append_run("resolve acme/widgets#6", "start", kind="resolve", target="acme/widgets#6")
    app = CrewApp(home / ".agent" / "tasks", Filters(repo="all"), interval=600, gh=github(SEEDED, []), clock=lambda: NOW)
    assert snap_compare(app, terminal_size=size, run_before=ready)
