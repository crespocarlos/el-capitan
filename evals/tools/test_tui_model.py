#!/usr/bin/env python3
"""The crew TUI (`crew.tui`): its view model over seeded task directories, `--once` without Textual, one pilot
smoke (Textual comes with the `tui` dependency group), and one status move run for real against a temp task.
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
from task_fixture import record_status

from crew.task import crew_task
from crew.tui import tui_model
from crew.tui.tui_model import CREW_TASK, SHIPPED_NOTE, STALE_NOTE, Filters, collect, landed_for, moves, parse_filter

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
    ("running", ("#12", "#9", "1/2", "running implement", "259k", "-", ""), {"ISSUE": ISSUE, "PR": PR.format(9)}),
    ("blocked", ("-", "-", "-", "stuck review", "-", "-", "BLOCKED: waiting for keys"), {}),
    ("idle", ("-", "-", "-", "running implement", "~259k", "-", "stale"), {}),
    ("shipped", ("-", "2 PRs", "-", "idle 2d", "1.1M", "?", ""), {"PR": PR.format(8)}),
])
def test_task_cells(home: Path, slug: str, cells: tuple, links: dict) -> None:
    """ISSUE, PR, PROGRESS, ACTIVITY (an open stage, a live lock, a stage past 6 h, the last entry), TOKENS (agents'
    new tokens, none, a `tokens_reported` as `~`, millions), LANDED, NOTE."""
    view = views(home, Filters(done=True))["tasks"]
    index = [row[1] for row in view.rows].index(slug)
    assert view.header[3:] == ("ISSUE", "PR", "PROGRESS", "ACTIVITY", "TOKENS", "LANDED", "NOTE")
    assert (view.rows[index][3:], view.links[index]) == (cells, links)


@pytest.mark.parametrize("filters,total", [
    (Filters(), "tokens: new ~518k, cache reads 401k across 3 tasks shown"),
    (Filters(done=True), "tokens: new ~1.6M, cache reads 404k across 4 tasks shown"),
    (Filters(repo="gadgets"), "tokens: new -, cache reads - across 1 tasks shown"),
])
def test_the_total_line_sums_the_rows_shown(home: Path, filters: Filters, total: str) -> None:
    """The total follows the filters: DONE rows and another repository change it."""
    assert total in views(home, filters)["tasks"].notes


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
    """One running agent shows in ACTIVITY and the workers view; two add up; TOKENS and the total never change."""
    tasks = home / ".agent" / "tasks"
    transcript(home, "b1", str(tasks / "T1"), 46)
    before = views(home, Filters())
    running = before["tasks"].rows[0]
    assert running[1] == "running" and running[6:8] == ("running implement · 92k", "259k"), running
    assert ("agent", "running", "agent-b1", "1m", "new 92k, cache reads 2.3M") in before["workers"].rows
    transcript(home, "b2", str(tasks / "T1"), 44, session="s2")
    after = views(home, Filters())
    assert after["tasks"].rows[0][6:8] == ("running implement · 2 · 180k", "259k")
    assert before["tasks"].notes == after["tasks"].notes, "live figures never reach the total"


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
        activity = [row for row in views(home, Filters())["tasks"].rows if row[1] == "blocked"][0][6]
    finally:
        path.chmod(0o644)
    assert activity == ("running review · 10k" if shown else "stuck review"), activity


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


def test_the_explicit_landed_read(home: Path) -> None:
    landed = landed_for(home / ".agent" / "tasks", Filters(done=True), reader)
    shipped = [row for row in views(home, Filters(done=True), landed)["tasks"].rows if row[1] == "shipped"]
    assert shipped[0][8] == "yes"


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


BLOCK, CLOSE = ("blocked", "{t}", "why"), ("mark-done", "{t}", "--force", "--pr-url", STALE_NOTE)


@pytest.mark.parametrize("state,prs,expected", [
    ("DRAFTING", [], [("mark-approved", "{t}"), BLOCK, CLOSE]),
    ("APPROVED", [], [("mark-implementing", "{t}", "--branch", "feat/x"), BLOCK, CLOSE]),
    ("IMPLEMENTING", [PR.format(7), PR.format(8)], [("mark-done", "{t}", "--pr-url", PR.format(8)), BLOCK]),
    ("IMPLEMENTING", [], [BLOCK, (*CLOSE[:-1], SHIPPED_NOTE)]),
    ("ON-HOLD", [], [BLOCK, CLOSE]),
    ("ABANDONED", [], [BLOCK]),
    ("DONE", [PR.format(8)], []),
])
def test_moves_per_state(tmp: Path, state: str, prs: list[str], expected: list[tuple]) -> None:
    """The gate the state allows (mark done with the newest PR), then `blocked` for every task not DONE and close as
    done (`--force`, the note `none (committed to main)` for IMPLEMENTING, else `closed: stale`) for a closable state
    with no PR; ABANDONED is not closable. Every move is a subcommand crew-task.py has."""
    found = moves(state, tmp, prs, "feat/x")
    wanted = [[arg.format(t=tmp) for arg in args] for args in expected]
    assert [move.argv(move.default or "why")[3:] for move in found] == wanted
    choices = crew_task.make_parser()._subparsers._group_actions[0].choices
    assert all(move.args[0] in choices for move in found)


def test_a_move_runs_crew_task_for_real(home: Path) -> None:
    """The app's default runner on a temp task: APPROVED to IMPLEMENTING in SPEC.md through crew-task.py, the spec's
    `## Branch:` recorded and, run outside any checkout of the task, no `worktree`."""
    from crew.tui.tui_app import run_command

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
    from crew.tui.tui_app import run_command

    spec = home / ".agent" / "tasks" / "T2" / "SPEC.md"
    spec.write_text(spec.read_text().replace("## Status\nAPPROVED", "## Status\nIMPLEMENTING"))
    view = views(home, Filters(repo="all"))["tasks"]
    row = next(i for i, cells in enumerate(view.rows) if cells[1].startswith("blocked"))
    assert view.rows[row][0] == "TAMPERED (spec says IMPLEMENTING, crew-task recorded APPROVED)", view.rows[row]
    assert [(move.args[0], *move.args[2:], move.ask) for move in view.moves[row]] == [
        ("restore-status", ""), ("restore-status", "--accept", "note")], view.moves[row]
    code, _, err = run_command(view.moves[row][0].argv())
    assert code == 0 and "## Status\nAPPROVED" in spec.read_text(), err


@pytest.mark.parametrize("spec_line", ["", "## Branch: [type/short-description — e.g. feat/x]\n\n"])
def test_no_start_move_without_a_spec_branch(home: Path, spec_line: str) -> None:
    """An APPROVED task whose SPEC.md has no `## Branch:`, or only the template's placeholder, gets no start move (only
    `blocked` and close as done) and a note saying to start it from its checkout."""
    spec = home / ".agent" / "tasks" / "T2" / "SPEC.md"
    spec.write_text(spec.read_text().replace("## Branch: feat/gadgets\n\n", spec_line))
    view = views(home, Filters(repo="all"))["tasks"]
    row = next(i for i, cells in enumerate(view.rows) if cells[1].startswith("blocked"))
    found = [(move.args[0], *move.args[2:3]) for move in view.moves[row]]
    assert found == [("blocked",), ("mark-done", "--force")], view.moves[row]
    assert any("no start move for blocked" in note and "from its checkout" in note for note in view.notes), view.notes


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


@pytest.mark.timeout(300)  # a nested run allowed 60 s
def test_once_prints_every_view_without_textual(home: Path) -> None:
    """`-S` leaves site-packages off the path, so Textual cannot be imported even where it is installed."""
    argv = [sys.executable, "-S", "-m", "crew.tui.crew_tui", "--once", "--repo", "all", "--tasks-dir", str(home / ".agent" / "tasks")]
    done = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, "TERM": "dumb", "PYTHONPATH": str(SRC)}, cwd=home,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    assert all(f"== {name} ==" in done.stdout for name in ("tasks", "workers", "report")) and "running" in done.stdout
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
    (held / ".task-id").write_text(json.dumps({"slug": "the-tokens-of-running-agents-x",
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


def test_app_switches_views_filters_moves_and_never_writes(home: Path) -> None:
    """Textual is in the `evals/test.sh` environment, so a missing one fails here rather than skipping.
    `s` on the one APPROVED task: cancel runs nothing; confirm runs the exact argv and shows the refusal;
    `blocked` asks for its reason first."""
    from crew.tui.tui_app import CrewApp

    tasks = home / ".agent" / "tasks"
    before = {path: path.stat().st_mtime for path in tasks.rglob("*")}

    opened: list[str] = []
    ran: list[list[str]] = []

    def runner(argv: list[str]) -> tuple[int, str, str]:
        ran.append(argv)
        return 1, "", "error: blocked is APPROVED, not DRAFTING; nothing written"

    async def drive() -> tuple[list[tuple[str, int]], dict | None, str, list]:
        app = CrewApp(tasks, Filters(repo="all"), interval=60, reader=reader, opener=opened.append, runner=runner)
        seen = []
        async with app.run_test() as pilot:
            await pilot.press("o", "O")
            cell = str(app.query_one("#table").get_cell_at((0, 3)))
            tokens = str(app.query_one("#table").get_cell_at((0, 7)))
            assert tokens == "259k" and "tokens: new ~518k" in str(app.query_one("#notes").render()), tokens
            for keys in (["r"], ["w"], ["p"], ["t", "a"], ["g"], ["slash", *"status:approved", "enter"]):
                await pilot.press(*keys)
                if keys == ["g"]:
                    await app.workers.wait_for_complete()
                    await pilot.pause()
                    landed = app.landed
                    continue
                seen.append((app.view_name, app.query_one("#table").row_count))
            await pilot.press("s", "enter", "n")
            cancelled = list(ran)
            await pilot.press("s", "enter", "y")
            await pilot.pause()
            notes = str(app.query_one("#notes").render())
            await pilot.press("s", "down", "enter", "enter", *"no keys", "enter", "y")  # an empty reason is refused
        return seen, landed, cell, [cancelled, notes]

    seen, landed, cell, (cancelled, notes) = asyncio.run(drive())
    start = [*CREW_TASK, "mark-implementing", str(tasks / "T2"), "--branch", "feat/gadgets"]
    assert cancelled == [] and ran == [start, [*CREW_TASK, "blocked", str(tasks / "T2"), "no keys"]]
    assert "not DRAFTING; nothing written" in notes and "exit 1" in notes, notes
    assert opened == [ISSUE, PR.format(9)], "o opens the selected task's issue and O its PR"
    assert cell == f"[link={ISSUE}]#12[/link]", "the issue cell is a terminal link"
    assert [name for name, _ in seen] == ["tasks", "workers", "report", "tasks", "tasks"]
    assert [count for _, count in seen][0] == 3 and seen[3][1] == 4 and seen[4][1] == 1, seen
    assert landed == {str(tasks / "T4"): "yes"}, "g reads the DONE rows' PRs in a worker, then reloads"
    assert {path: path.stat().st_mtime for path in tasks.rglob("*")} == before
