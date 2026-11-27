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


def seed(home: Path) -> Path:
    """Tasks: running, blocked with a dead stage, stale, done with a PR; worktrees: fresh, stale, malformed, no lock."""
    tasks = home / ".agent" / "tasks"
    specs = (
        ("T1", "running", "IMPLEMENTING", "acme/widgets",
         [(5, "METRIC: stage_start stage=review"), (4, "METRIC: stage_end stage=review"),
          (2, "METRIC: stage_start stage=implement workers=2")]),
        ("T2", "blocked", "APPROVED", "acme/gadgets",
         [(8, "METRIC: stage_start stage=review"), (1, "BLOCKED: waiting for keys")]),
        ("T3", "idle", "IMPLEMENTING", "acme/widgets", [(20 * 24, "TRANSITION: APPROVED → IMPLEMENTING")]),
        ("T4", "shipped", "DONE", "acme/widgets",
         [(3, "METRIC: stage_start stage=review"), (2, "PR opened: https://github.com/acme/widgets/pull/7")]),
    )
    for uuid, slug, status, repo, progress in specs:
        task = tasks / uuid
        task.mkdir(parents=True)
        (task / "SPEC.md").write_text(f"# {slug}\n\n## Status\n{status}\n")
        (task / ".task-id").write_text(json.dumps({"slug": slug, "repo_remote_url": f"git@github.com:{repo}.git"}))
        (task / "PROGRESS.md").write_text("".join(f"[{stamp(h)}] {line}\n" for h, line in progress))
        old = NOW - max(h for h, _ in progress) * HOUR
        for path in task.iterdir():
            os.utime(path, (old, old))
    locks = (("fresh", f"task=T1\nstarted={int(NOW - 600)}\n"), ("old", f"task=T9\nstarted={int(NOW - 7 * HOUR)}\n"),
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


@pytest.mark.parametrize("filters,slugs", [
    (Filters(), ["running", "idle", "blocked"]),
    (Filters(repo="widgets", done=True), ["running", "idle", "shipped"]),
])
def test_tasks_view_order_and_done_rows(home: Path, filters: Filters, slugs: list[str]) -> None:
    assert [row[1] for row in views(home, filters)["tasks"].rows] == slugs


def test_task_cells_and_the_explicit_landed_read(home: Path) -> None:
    unread = {row[1]: row for row in views(home, Filters(done=True))["tasks"].rows}
    assert (unread["blocked"][5], unread["idle"][5], unread["running"][5]) == ("BLOCKED: waiting for keys", "stale", "")
    assert (unread["shipped"][4], unread["running"][4]) == ("?", "-")
    landed = landed_for(home / ".agent" / "tasks", Filters(done=True), reader)
    shipped = [row for row in views(home, Filters(done=True), landed)["tasks"].rows if row[1] == "shipped"]
    assert shipped[0][4] == "yes"


def test_workers_view_lists_running_stages_and_locks(home: Path) -> None:
    rows = views(home, Filters())["workers"].rows
    assert [row[:3] + row[4:] for row in rows] == [
        ("stage", "running", "implement", "workers=2"),
        ("stage", "blocked", "review", "stale: no stage_end"),
        ("lock", "T9", str(home / "old"), "stale: the guard ignores it"),
        ("lock", "running", str(home / "fresh"), "live"),
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


def test_app_switches_views_filters_and_never_writes(home: Path) -> None:
    """Textual is in the `evals/test.sh` environment, so a missing one fails here rather than skipping."""
    from tui_app import CrewApp

    tasks = home / ".agent" / "tasks"
    before = {path: path.stat().st_mtime for path in tasks.rglob("*")}

    async def drive() -> tuple[list[tuple[str, int]], dict | None]:
        app = CrewApp(tasks, Filters(repo="all"), interval=60, reader=reader)
        seen = []
        async with app.run_test() as pilot:
            for keys in (["r"], ["w"], ["p"], ["t", "a"], ["g"], ["slash", *"status:approved", "enter"]):
                await pilot.press(*keys)
                if keys == ["g"]:
                    await app.workers.wait_for_complete()
                    await pilot.pause()
                    landed = app.landed
                    continue
                seen.append((app.view_name, app.query_one("#table").row_count))
        return seen, landed

    seen, landed = asyncio.run(drive())
    assert [name for name, _ in seen] == ["tasks", "workers", "report", "tasks", "tasks"]
    assert [count for _, count in seen][0] == 3 and seen[3][1] == 4 and seen[4][1] == 1, seen
    assert landed == {str(tasks / "T4"): "yes"}, "g reads the DONE rows' PRs in a worker, then reloads"
    assert {path: path.stat().st_mtime for path in tasks.rglob("*")} == before
