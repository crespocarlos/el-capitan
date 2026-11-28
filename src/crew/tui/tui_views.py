"""The TUI's tabs as plain rows, from data already read (`Snapshot`); pure. `ongoing`: every open task, the "needs
you" ones first, each expandable (`expanded`) into its spec's phases or its PRs; `summary`: every task with its issue
and PRs, newest first; `runs`: stages, locks, live agents and standalone runs; `cost`: `crew
report`. Rows are keyed by task, child rows by `<task>::<n>`; `details` fills the detail pane."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from crew.core.task.ls_data import stale
from crew.core.task.ls_report import cursor_sessions, stage_pairs
from crew.core.task.ls_report import render as render_report
from crew.core.task.task_cost import session_text
from crew.core.task.task_gc import stamp_of
from crew.core.task.task_live import Live
from crew.core.task.task_lock import LOCK_STALE_SECONDS, Lock
from crew.core.task.task_progress import blocked_reason, count_text, sum_usage, task_usage_totals, usage_text
from crew.core.task.task_report import CLOSED_OUTSIDE, held_from, number_cell, ordered_rows, task_cells
from crew.core.task.task_state import DONE_ITEM, OPEN_ITEM, TaskState, closed_outside, head, name, spec_branch, tampered
from crew.tui.tui_github import Facts, issue_cell, pr_cell
from crew.tui.tui_moves import Move, moves, restore_moves

VIEWS = ("ongoing", "summary", "runs", "cost")

TABS = {"ongoing": "1 Ongoing", "summary": "2 Tasks · PRs · Issues", "runs": "3 Runs"}

STAGE_STALE_SECONDS = LOCK_STALE_SECONDS  # a stage open this long outlived any worker the guard still protects

LINKED = ("ISSUE", "PR")  # the URLs a row carries; `o` and `O` open them, `y` copies the PR's

NEEDS_YOU = "! "  # before the STATE of a BLOCKED or TAMPERED task, pinned first in Ongoing

CLOSED_MARK, OPEN_MARK, CHILD = "▸ ", "▾ ", "  └ "  # a row with children, collapsed and expanded; a child's TASK

RUNS_SHOWN = 20  # the newest standalone runs the Runs tab lists

# A `### Phase …` heading whose last backtick span is its branch: `### Phase 7b: TUI views (`feat/tui-views`)`.
PHASE = re.compile(r"^###[ \t]+(Phase\b[^\n]*?)[ \t(]*`([^`\n]+)`[^`\n]*$", re.M)

NEXT_HEADING = re.compile(r"^#{1,3} ", re.M)


@dataclass(frozen=True)
class Child:
    """A row under a task: one phase of its spec or one of its PRs, with that PR's URL."""

    key: str
    cells: tuple[str, ...]
    url: str = ""


@dataclass
class View:
    """One screen: a title, a table header and rows of plain cells, note lines under the table, and per row its key
    (the task dir, the worker or the run), the URL behind each linked cell (`{"ISSUE": url, "PR": url}`) and its moves;
    `children` per task key (shown by `expanded`), `details` per task key (the detail pane), `count` for the tab."""

    title: str
    header: tuple[str, ...]
    rows: list[tuple[str, ...]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    moves: list[list[Move]] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    children: dict[str, list[Child]] = field(default_factory=dict)
    details: dict[str, list[str]] = field(default_factory=dict)
    count: int = 0


@dataclass(frozen=True)
class Phase:
    """One `### Phase …` section of a spec: its name, branch, and checked and total criteria in the section."""

    name: str
    branch: str
    done: int
    total: int


def phases(text: str) -> list[Phase]:
    """The spec's phases, in order; each counts the checkboxes up to the next heading of level 1 to 3."""
    found = []
    for match in PHASE.finditer(text):
        after = NEXT_HEADING.search(text, match.end())
        section = text[match.end() : after.start() if after else len(text)]
        done = len(DONE_ITEM.findall(section))
        found.append(Phase(match.group(1).strip().rstrip(":"), match.group(2), done, done + len(OPEN_ITEM.findall(section))))
    return found


def phase_prs(r: TaskState, found: list[Phase], facts: Facts) -> list[str]:
    """Each phase's PR among the task's, matched by branch (`headRefName` in the facts); "" for none known yet."""
    by_branch = {facts.prs[url]["head"]: url for url in r.prs if url in facts.prs}
    return [by_branch.get(phase.branch, "") for phase in found]


def phase_at(found: list[Phase], prs: list[str], facts: Facts) -> int:
    """The 1-based phase in progress: the first whose PR is not merged (with no PR, whose criteria are not all
    checked); the last when every phase is done."""
    for index, (phase, url) in enumerate(zip(found, prs, strict=True)):
        merged = url and facts.prs.get(url, {}).get("state") == "MERGED"
        if not (merged or (not url and phase.total and phase.done == phase.total)):
            return index + 1
    return len(found)


def ago(seconds: float) -> str:
    """A duration as `5m`, `3h` or `2d`."""
    minutes = max(0, int(seconds // 60))
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h" if minutes < 24 * 60 else f"{minutes // (24 * 60)}d"


def live_text(agents: list[Live]) -> str:
    """The LIVE cell: the running agents' new tokens so far, `92k`, or `2 · 180k` for two; `-` for none."""
    total = count_text(sum(agent.new for agent in agents))
    return "-" if not agents else total if len(agents) == 1 else f"{len(agents)} · {total}"


@dataclass(frozen=True)
class Snapshot:
    """What every view reads: each task's PROGRESS entries, the worker locks, the moment, the running agents per task
    (`task_live`), the GitHub facts, and the runs ledger (`lib/runs.read_runs`)."""

    entries: dict[Path, list]
    locks: list[Lock]
    now: float
    live: dict[Path, list[Live]] = field(default_factory=dict)
    facts: Facts = field(default_factory=Facts)
    runs: list[dict] = field(default_factory=list)


def short_repo(rows: list[TaskState]) -> Callable[[TaskState], str]:
    """REPO without the owner every row shares, so TASK keeps the width."""
    owners = {r.repo.split("/", 1)[0] for r in rows if "/" in r.repo}
    shared = len(owners) == 1 and all("/" in r.repo for r in rows if r.repo)
    return lambda r: (r.repo.split("/", 1)[1] if shared and "/" in r.repo else r.repo) or "-"


def pr_children(r: TaskState, found: list[Phase], facts: Facts, header: tuple[str, ...]) -> list[Child]:
    """One child per phase (`found`, the spec's), else per PR when there are several: TASK names it, REPO its
    branch, PR its cell, PROGRESS a phase's criteria."""
    if found:
        items = [(p.name, p.branch, url, f"{p.done}/{p.total}" if p.total else "-") for p, url in zip(found, phase_prs(r, found, facts), strict=True)]
    elif len(r.prs) > 1:
        items = [(facts.prs.get(url, {}).get("title") or number_cell(url), facts.prs.get(url, {}).get("head", "-"), url, "") for url in reversed(r.prs)]
    else:
        return []
    children = []
    for index, (label, branch, url, progress) in enumerate(items):
        cells = {
            "TASK": CHILD + label,
            "REPO": branch,
            "PR": pr_cell(url, facts) if url else "-",
            "PRS": pr_cell(url, facts) if url else "-",
            "PROGRESS": progress,
        }
        children.append(Child(f"{r.task}::{index}", tuple(cells.get(column, "") for column in header), url))
    return children


def pr_summary(r: TaskState, found: list[Phase], facts: Facts) -> str:
    """A task row's PR cell: `phase k/n` for a spec with phases, the one PR's cell, `N PRs`, or `-`."""
    if found:
        return f"phase {phase_at(found, phase_prs(r, found, facts), facts)}/{len(found)}"
    return pr_cell(r.prs[0], facts) if len(r.prs) == 1 else f"{len(r.prs)} PRs" if r.prs else "-"


def wanted(r: TaskState, words: tuple[str, ...]) -> bool:
    """True when every filter word is in the task's name, repository, state, or issue and PR numbers."""
    text = " ".join([name(r), r.repo, head(r), number_cell(r.issue), *map(number_cell, r.prs)]).lower()
    return all(word in text for word in words)


def row_links(r: TaskState) -> dict[str, str]:
    """The task row's issue and newest PR, for `o`, `O` and `y`."""
    return {key: url for key, url in (("ISSUE", r.issue), ("PR", r.prs[-1] if r.prs else "")) if url}


def needs_you(r: TaskState) -> bool:
    return bool(tampered(r) or blocked_reason(r.task))


def details(r: TaskState, seen: Snapshot) -> list[str]:
    """The detail pane (`p`): the issue and every PR, the branch, progress and open criteria, tokens, the last 5
    PROGRESS entries, the moves and the paths."""
    facts, home, entries = seen.facts, str(Path.home()), seen.entries.get(r.task, [])
    cells = task_cells(r, entries, seen.locks, seen.now, task_usage_totals(entries), bool(seen.live.get(r.task)))
    lines = [f"{name(r)} · {tampered(r) or head(r) or '?'} · {r.repo or '-'}"]
    if r.issue:
        lines.append(f"issue {issue_cell(r.issue, facts)} {facts.issues.get(r.issue, {}).get('title', '')}".rstrip())
    for url in reversed(r.prs):
        record = facts.prs.get(url, {})
        branches = f" · {record['head']} → {record['base']}" if record else ""
        lines.append(f"PR {pr_cell(url, facts)}{branches} {record.get('title', '')}".rstrip())
    lines.append(f"branch: {spec_branch(r.text) or r.meta.get('branch') or '-'}")
    criteria = [line.strip() for line in r.text.splitlines() if OPEN_ITEM.match(line)]
    lines.append(f"progress {cells['PROGRESS']}; {len(criteria)} open criteria")
    lines += [f"  {line[:100]}" for line in criteria[:5]]
    lines.append(f"tokens: recorded {cells['TOKENS']}, live {live_text(seen.live.get(r.task, []))}")
    lines += ["recent:", *(f"  {entry.text[:100]}" for entry in entries[-5:])]
    available = [m for m in (restore_moves(r) if tampered(r) else moves(head(r), r.task, r.prs, spec_branch(r.text))) if not m.why]
    lines.append("moves: " + (", ".join(f"[{m.key}] {m.label}" for m in available) or "none"))
    worktree = r.meta.get("worktree")
    lines.append(f"task: {r.task}" + (f"\nworktree: {worktree}" if worktree else ""))
    return [line.replace(home, "~") for line in lines]


def ongoing_view(rows: list[TaskState], scope: str, seen: Snapshot) -> View:
    """Every task not DONE: BLOCKED and TAMPERED ones first (STATE starts `! `), then `crew ls` order. STATE, TASK,
    REPO, ISSUE (with its state), PR (`tui_github.pr_cell`, `phase k/n` or `N PRs`), PROGRESS, ACTIVITY, LIVE (the
    running agents' tokens, apart from TOKENS and the total), TOKENS and a NOTE (`was <state>` of an ON-HOLD task, the
    BLOCKED reason, or `stale` past 14 idle days); then the tokens of the rows shown."""
    view = View("ongoing", ("STATE", "TASK", "REPO", "ISSUE", "PR", "PROGRESS", "ACTIVITY", "LIVE", "TOKENS", "NOTE"))
    open_rows = [r for r in rows if head(r) != "DONE"]
    pinned = sorted((r for r in open_rows if needs_you(r)), key=lambda r: r.activity)
    shown = pinned + [r for r in ordered_rows(open_rows, False) if r not in pinned]
    repo, totals = short_repo(shown), []
    for r in shown:
        reason, held = blocked_reason(r.task), held_from(r)
        note = "; ".join(filter(None, [f"was {held}" if held else "", f"BLOCKED: {reason}" if reason else ("stale" if stale(r) else "")]))
        entries = seen.entries.get(r.task, [])
        totals.append(task_usage_totals(entries))
        cells = task_cells(r, entries, seen.locks, seen.now, totals[-1], bool(seen.live.get(r.task)))
        found = phases(r.text)
        cells.update(LIVE=live_text(seen.live.get(r.task, [])), ISSUE=issue_cell(r.issue, seen.facts), PR=pr_summary(r, found, seen.facts))
        state = (NEEDS_YOU if r in pinned else "") + (tampered(r) or head(r) or "?")
        view.rows.append((state, name(r), repo(r), *(cells[key] for key in view.header[3:9]), note))
        key = str(r.task)
        view.keys.append(key)
        view.links.append(row_links(r))
        view.moves.append(restore_moves(r) if tampered(r) else moves(head(r), r.task, r.prs, spec_branch(r.text)))
        view.children[key] = pr_children(r, found, seen.facts, view.header)
    view.count = len(shown)
    view.notes.append(f"{len(shown)} open tasks ({len(pinned)} need you); scope: {scope}")
    view.notes.append(f"tokens: {usage_text(sum_usage(totals))} across {len(shown)} tasks shown")
    sessions = cursor_sessions({r.task: seen.entries.get(r.task, []) for r in shown}, None)
    if sessions:
        view.notes.append(f"{session_text(sessions)} across the tasks shown, apart from TOKENS")
    return view


def summary_view(rows: list[TaskState], seen: Snapshot) -> View:
    """Read only: every task, DONE included, newest first: TASK, REPO, STATE, ISSUE with its state, and one compact
    cell per PR (`#52 ✓merged landed  #56 ●open CI✗`); a task with several PRs expands into one row per PR."""
    view = View("summary", ("TASK", "REPO", "STATE", "ISSUE", "PRS"))
    shown = sorted(rows, key=lambda r: (r.activity, name(r)))
    repo = short_repo(shown)
    for r in shown:
        state = f"DONE ({CLOSED_OUTSIDE})" if closed_outside(r) else tampered(r) or head(r) or "?"
        prs = "  ".join(pr_cell(url, seen.facts) for url in reversed(r.prs)) or "-"
        view.rows.append((name(r), repo(r), state, issue_cell(r.issue, seen.facts), prs))
        key = str(r.task)
        view.keys.append(key)
        view.links.append(row_links(r))
        view.moves.append([])
        view.children[key] = pr_children(r, [], seen.facts, view.header)
    view.count = len(shown)
    done = sum(1 for r in rows if head(r) == "DONE")
    view.notes.append(f"{len(rows)} tasks: {len(rows) - done} open, {done} done; {sum(len(r.prs) for r in rows)} PRs")
    return view


def runs_view(rows: list[TaskState], seen: Snapshot) -> View:
    """Running stages (from PROGRESS) and worker locks, each with its age (past 6 h either is stale), each running
    agent (`task_live`) with the time since its transcript last moved and its tokens so far; then the newest standalone
    runs of the ledger (no task): KIND (`review pr`, `resolve pr`, `review self`), TARGET (`owner/repo#n`), WHAT
    (running, done, or `no end recorded` past 6 h), AGE since it started, NOTE (the verdict and report, or the PR)."""
    view = View("runs", ("KIND", "TARGET", "WHAT", "AGE", "NOTE"))
    entries, locks, now, live = seen.entries, seen.locks, seen.now, seen.live

    def add(key: str, *row: str, link: str = "") -> None:
        view.keys.append(key)
        view.rows.append(row)
        view.links.append({"PR": link} if link else {})

    for r in (r for r in rows if head(r) != "DONE"):
        for stage, (at, given) in stage_pairs(entries.get(r.task, []))[1].items():
            detail = [" ".join(f"{k}={v}" for k, v in given.items() if k not in ("stage", "session"))]
            stale_note = ["stale: no stage_end"] if now - at.timestamp() >= STAGE_STALE_SECONDS else []
            add(f"stage {r.task} {stage}", "stage", name(r), stage, ago(now - at.timestamp()), "; ".join(filter(None, detail + stale_note)))
    slugs, home = {r.uuid: name(r) for r in rows}, str(Path.home())
    for lock in sorted(locks, key=lambda lock: lock.started):
        state = "stale: the guard ignores it" if now - lock.started >= LOCK_STALE_SECONDS else "live"
        add(f"lock {lock.tree}", "lock", slugs.get(lock.task, lock.task), str(lock.tree).replace(home, "~"), ago(now - lock.started), state)
    tasks = {r.task: name(r) for r in rows}
    for agent in sorted((agent for agents in live.values() for agent in agents), key=lambda a: a.modified):
        used = f"new {count_text(agent.new)}, cache reads {count_text(agent.cache_read)}"
        add(f"agent {agent.path}", "agent", tasks.get(agent.task, str(agent.task)), f"agent-{agent.agent_id}", ago(now - agent.modified), used)
    standalone = [run for run in seen.runs if not run.get("task")][-RUNS_SHOWN:]
    for run in reversed(standalone):
        age = now - (stamp_of(run["started"]) or 0)
        state = "done" if "outcome" in run else "running" if age < STAGE_STALE_SECONDS else "no end recorded"
        target = run.get("target", "-")
        repo, _, number = target.partition("#")
        pr = f"https://github.com/{repo}/pull/{number}" if number else ""
        note = " · ".join(filter(None, [run.get("outcome", ""), run.get("report", pr).replace(home, "~")]))
        add(f"run {run['id']}", f"{run.get('kind', '?')} {run.get('mode', 'pr')}", target, state, ago(age), note, link=pr)
    view.notes = [] if view.rows else ["no stage, worker lock, agent or standalone run to show"]
    view.moves = [[] for _ in view.rows]
    view.count = len(view.rows)
    return view


def report_view(report: dict, scope: str) -> View:
    """The cost screen (`c`): `crew report` as one line per row."""
    lines = render_report(report, scope)
    count = len(lines)
    return View("cost", ("REPORT",), [(line,) for line in lines], links=[{}] * count, moves=[[]] * count, keys=list(map(str, range(count))))


def build(rows: list[TaskState], words: tuple[str, ...], scope: str, report: dict, seen: Snapshot) -> dict[str, View]:
    """Every tab from data already read; the filter words narrow the task tabs."""
    shown = [r for r in rows if wanted(r, words)]
    views = {
        "ongoing": ongoing_view(shown, scope, seen),
        "summary": summary_view(shown, seen),
        "runs": runs_view(rows, seen),
        "cost": report_view(report, scope),
    }
    views["ongoing"].details = views["summary"].details = {str(r.task): details(r, seen) for r in shown}
    return views


def expanded(view: View, opened: set[str]) -> View:
    """The view with each opened task's children under it; TASK marks a row that has children `▸` (closed) or `▾`."""
    at = view.header.index("TASK") if "TASK" in view.header else -1
    out = replace(view, rows=[], links=[], moves=[], keys=[])
    for row, link, move, key in zip(view.rows, view.links, view.moves, view.keys, strict=True):
        kids = view.children.get(key, [])
        if kids and at >= 0:
            row = (*row[:at], (OPEN_MARK if key in opened else CLOSED_MARK) + row[at], *row[at + 1 :])
        out.rows.append(row)
        out.links.append(link)
        out.moves.append(move)
        out.keys.append(key)
        for child in kids if key in opened else []:
            out.rows.append(child.cells)
            out.links.append({"PR": child.url} if child.url else {})
            out.moves.append([])
            out.keys.append(child.key)
    return out
