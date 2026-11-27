#!/usr/bin/env python3
"""The crew TUI (`tui/`): its view model over seeded task directories, `--once` without Textual, one pilot smoke.

A file of its own because `tui/` sits outside `.agent/tools` and no other suite loads it. The pilot
smoke runs when Textual is importable (`evals/test.sh` adds the pin in `tui/requirements.txt`).
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from cli_runner import load

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "tui" / "crew_tui.py"
load(ENTRY)
import tui_model  # noqa: E402
from tui_model import Filters, collect, landed_for, parse_filter  # noqa: E402

NOW = time.time()
HOUR = 3600


def stamp(hours_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - hours_ago * HOUR))


ISSUE = "https://github.com/acme/widgets/issues/12"
PR = "https://github.com/acme/widgets/pull/{}"


def seed(home: Path) -> Path:
    """Tasks: running with an issue and a PR, blocked with a dead stage, stale under a live lock, done with two PRs;
    worktrees: fresh, stale, malformed, no lock."""
    tasks = home / ".agent" / "tasks"
    specs = (
        ("T1", "running", "IMPLEMENTING", "acme/widgets", f"Issue: {ISSUE}\n\n- [x] a\n- [ ] b\n",
         [(5, "METRIC: stage_start stage=review"), (4, "METRIC: stage_end stage=review"),
          (2, "METRIC: stage_start stage=implement workers=2"), (2, f"PR: {PR.format(9)}")]),
        ("T2", "blocked", "APPROVED", "acme/gadgets", "",
         [(8, "METRIC: stage_start stage=review"), (1, "BLOCKED: waiting for keys")]),
        ("T3", "idle", "IMPLEMENTING", "acme/widgets", "", [(20 * 24, "TRANSITION: APPROVED → IMPLEMENTING")]),
        ("T4", "shipped", "DONE", "acme/widgets", "",
         [(50, "METRIC: stage_start stage=review"), (49, f"PR opened: {PR.format(7)}"), (49, f"PR: {PR.format(8)}")]),
    )
    for uuid, slug, status, repo, body, progress in specs:
        task = tasks / uuid
        task.mkdir(parents=True)
        (task / "SPEC.md").write_text(f"# {slug}\n\n## Status\n{status}\n\n{body}")
        (task / ".task-id").write_text(json.dumps({"slug": slug, "repo_remote_url": f"git@github.com:{repo}.git"}))
        (task / "PROGRESS.md").write_text("".join(f"[{stamp(h)}] {line}\n" for h, line in progress))
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
    monkeypatch.chdir(tmp)
    seed(tmp)
    return tmp


def views(home: Path, filters: Filters, landed: dict[str, str] | None = None) -> dict:
    trees = [home / name for name in ("fresh", "old", "broken", "bare")]
    return collect(home / ".agent" / "tasks", filters, landed, trees=trees, here=lambda: {}, now=NOW)


def reader(argv: list[str]) -> tuple[int, str]:
    """A stub for the `gh` read: every PR merged into the default branch."""
    record = ({"state": "MERGED", "baseRefName": "main", "mergeCommit": {"oid": "abc"}} if argv[0] == "view"
              else {"defaultBranchRef": {"name": "main"}})
    return 0, json.dumps(record)


@pytest.mark.parametrize("config,filters,slugs", [
    (None, Filters(), ["running", "idle", "blocked"]),
    (None, Filters(repo="widgets", done=True), ["running", "idle", "shipped"]),
    ("acme/gadgets", Filters(), ["blocked"]),  # ls.repo is the scope when no repo is given
    ("acme/gadgets", Filters(repo="all"), ["running", "idle", "blocked"]),  # --repo wins
    ("acme/gadgets", Filters(repo="here"), ["running", "idle", "blocked"]),  # here: the cwd's, none outside a repo
])
def test_tasks_view_order_and_done_rows(home: Path, config: str | None, filters: Filters, slugs: list[str]) -> None:
    if config:
        (home / ".agent" / "config.json").write_text(json.dumps({"ls": {"repo": config}}))
    assert [row[1] for row in views(home, filters)["tasks"].rows] == slugs


@pytest.mark.parametrize("slug,cells,links", [
    ("running", ("#12", "#9", "1/2", "running implement", "-", ""), {"ISSUE": ISSUE, "PR": PR.format(9)}),
    ("blocked", ("-", "-", "-", "stuck review", "-", "BLOCKED: waiting for keys"), {}),
    ("idle", ("-", "-", "-", "running implement", "-", "stale"), {}),
    ("shipped", ("-", "2 PRs", "-", "idle 2d", "?", ""), {"PR": PR.format(8)}),
])
def test_task_cells(home: Path, slug: str, cells: tuple, links: dict) -> None:
    """ISSUE, PR, PROGRESS, ACTIVITY (an open stage, a live lock, a stage past 6 h, the last entry), LANDED, NOTE."""
    view = views(home, Filters(done=True))["tasks"]
    index = [row[1] for row in view.rows].index(slug)
    assert view.header[3:] == ("ISSUE", "PR", "PROGRESS", "ACTIVITY", "LANDED", "NOTE")
    assert (view.rows[index][3:], view.links[index]) == (cells, links)


def test_the_explicit_landed_read(home: Path) -> None:
    landed = landed_for(home / ".agent" / "tasks", Filters(done=True), reader)
    shipped = [row for row in views(home, Filters(done=True), landed)["tasks"].rows if row[1] == "shipped"]
    assert shipped[0][7] == "yes"


def test_workers_view_lists_running_stages_and_locks(home: Path) -> None:
    rows = views(home, Filters())["workers"].rows
    assert [row[:3] + row[4:] for row in rows] == [
        ("stage", "running", "implement", "workers=2"),
        ("stage", "blocked", "review", "stale: no stage_end"),
        ("lock", "T9", str(home / "old"), "stale: the guard ignores it"),
        ("lock", "idle", str(home / "fresh"), "live"),
    ]
    hook = (ROOT / ".claude" / "hooks" / "guard" / "worker-tree.sh").read_text()
    assert f"\nSTALE_SECONDS={tui_model.LOCK_STALE_SECONDS}\n" in hook, "the lock threshold follows worker-tree.sh"


@pytest.mark.parametrize("text,base,expected", [
    ("repo:acme/w status:implementing status:done done", None, Filters("acme/w", ("IMPLEMENTING", "DONE"), True)),
    ("status:approved", Filters("all", ("DONE",), True, 7), Filters("all", ("APPROVED",), True, 7)),
    ("status:bogus", None, ValueError),
    ("colour:red", None, ValueError),
])
def test_parse_filter(text: str, base: Filters | None, expected: object) -> None:
    if expected is ValueError:
        with pytest.raises(ValueError):
            parse_filter(text, base)
    else:
        assert parse_filter(text, base) == expected


def test_once_prints_every_view_without_textual(home: Path) -> None:
    """`-S` leaves site-packages off the path, so Textual cannot be imported even where it is installed."""
    argv = [sys.executable, "-S", str(ENTRY), "--once", "--repo", "all", "--tasks-dir", str(home / ".agent" / "tasks")]
    done = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, "TERM": "dumb"}, cwd=home,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    assert all(f"== {name} ==" in done.stdout for name in ("tasks", "workers", "report")) and "running" in done.stdout
    assert " #12 " in done.stdout and "[link" not in done.stdout, "--once prints the issue as plain text"


def test_app_switches_views_filters_and_never_writes(home: Path) -> None:
    """Textual is in the `evals/test.sh` environment, so a missing one fails here rather than skipping."""
    from tui_app import CrewApp

    tasks = home / ".agent" / "tasks"
    before = {path: path.stat().st_mtime for path in tasks.rglob("*")}

    opened: list[str] = []

    async def drive() -> tuple[list[tuple[str, int]], dict | None, str]:
        app = CrewApp(tasks, Filters(repo="all"), interval=60, reader=reader, opener=opened.append)
        seen = []
        async with app.run_test() as pilot:
            await pilot.press("o", "O")
            cell = str(app.query_one("#table").get_cell_at((0, 3)))
            for keys in (["r"], ["w"], ["p"], ["t", "a"], ["g"], ["slash", *"status:approved", "enter"]):
                await pilot.press(*keys)
                if keys == ["g"]:
                    await app.workers.wait_for_complete()
                    await pilot.pause()
                    landed = app.landed
                    continue
                seen.append((app.view_name, app.query_one("#table").row_count))
        return seen, landed, cell

    seen, landed, cell = asyncio.run(drive())
    assert opened == [ISSUE, PR.format(9)], "o opens the selected task's issue and O its PR"
    assert cell == f"[link={ISSUE}]#12[/link]", "the issue cell is a terminal link"
    assert [name for name, _ in seen] == ["tasks", "workers", "report", "tasks", "tasks"]
    assert [count for _, count in seen][0] == 3 and seen[3][1] == 4 and seen[4][1] == 1, seen
    assert landed == {str(tasks / "T4"): "yes"}, "g reads the DONE rows' PRs in a worker, then reloads"
    assert {path: path.stat().st_mtime for path in tasks.rglob("*")} == before
