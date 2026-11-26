#!/usr/bin/env python3
"""`crew ls --watch [--interval N]`: the table, redrawn every N seconds, read-only.

The data gathering lives in `ls_data.py` so a non-agentic TUI can import it too; this suite pins that
module (`gather`, `watch`), the loop's injectable sleep, clear and iteration cap, and the CLI end to end:
a real `crew-ls.py --watch` is started, draws, takes a SIGINT, exits 0, and leaves the task files alone.
"""
from __future__ import annotations

import hashlib
import json
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / ".agent" / "tools" / "task"
sys.path.insert(0, str(TASK_TOOLS))
sys.path.insert(0, str(TASK_TOOLS.parent))
FAILED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("pass: " if condition else "FAIL: ") + name + ("" if condition else f": {detail}"))
    if not condition:
        FAILED.append(name)


def make_tasks(base: Path) -> Path:
    tasks = base / "tasks"
    for uuid, slug, status in (("11111111-1111-1111-1111-111111111111", "shipped", "DONE"),
                               ("22222222-2222-2222-2222-222222222222", "building", "IMPLEMENTING")):
        task = tasks / uuid
        task.mkdir(parents=True)
        (task / "SPEC.md").write_text(f"# Spec: {slug}\n\n## Status\n{status}\n\n- [x] one\n- [ ] two\n", encoding="utf-8")
        (task / ".task-id").write_text(json.dumps({"slug": slug, "branch": f"feat/{slug}"}), encoding="utf-8")
        (task / "PROGRESS.md").write_text("BLOCKED: waiting\n" if slug == "building" else "", encoding="utf-8")
    return tasks


def digest(tasks: Path) -> str:
    material = hashlib.sha256()
    for path in sorted(tasks.rglob("*")):
        if path.is_file():
            material.update(str(path).encode() + path.read_bytes())
    return material.hexdigest()


def gathering(tmp: Path) -> None:
    import ls_data
    tasks = make_tasks(tmp)
    snapshot = ls_data.gather(tasks, show_done=False)
    names = sorted(r.task.name for r in snapshot.rows)
    check("gather returns every task row", names == ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"], names)
    check("gather returns the BLOCKED lines of open tasks", any("BLOCKED: waiting" in line for line in snapshot.blocked), snapshot.blocked)
    check("gather makes no landed read unless done tasks are shown", snapshot.landed == [], snapshot.landed)
    seen: list[list[str]] = []
    stub = lambda rows: seen.append([name for name, _ in rows]) or ["  shipped  landed: unknown"]
    shown = ls_data.gather(tasks, show_done=True, landed=stub)
    check("with done tasks shown, only DONE tasks are read for landed", seen == [["shipped"]] and shown.landed == ["  shipped  landed: unknown"], seen)
    check("a directory with no tasks gathers nothing", ls_data.gather(tmp / "empty", False).rows == [])


def limit_and_cache(tmp: Path) -> None:
    """`--limit` bounds the landed reads, a repository is asked once, and a watch loop re-reads on a TTL."""
    import ls_data
    tasks = tmp / "tasks"
    for index in range(4):
        task = tasks / f"{index:08d}-1111-1111-1111-111111111111"
        task.mkdir(parents=True)
        (task / "SPEC.md").write_text(f"# Spec: d{index}\n\n## Status\nDONE\n\n- [x] one\n", encoding="utf-8")
        (task / ".task-id").write_text(json.dumps({"slug": f"d{index}", "branch": f"feat/d{index}"}), encoding="utf-8")
        (task / "PROGRESS.md").write_text(f"[2026-01-01 00:00:00] TRANSITION: IMPLEMENTING → DONE (PR opened: https://github.com/acme/w/pull/{index + 1})\n",
                                          encoding="utf-8")
    seen: list[list[str]] = []
    stub = lambda rows: seen.append([n for n, _ in rows]) or [f"  {n}  landed: no" for n, _ in rows]
    ls_data.gather(tasks, show_done=True, landed=stub, limit=2)
    check("--limit is applied before the landed reads", len(seen) == 1 and len(seen[0]) == 2, seen)
    seen.clear()
    ls_data.gather(tasks, show_done=True, landed=stub)
    check("without a limit every DONE task is read", len(seen[0]) == 4, seen)
    calls: list[list[str]] = []

    def read(arguments: list[str]) -> tuple[int, str]:
        calls.append(arguments)
        if arguments[0] == "view":
            return 0, json.dumps({"state": "OPEN", "baseRefName": "main", "mergeCommit": None})
        return 0, json.dumps({"defaultBranchRef": {"name": "main"}})

    pairs = [(f"d{i}", t) for i, t in enumerate(sorted(tasks.iterdir()))]
    ls_data.landed_lines(pairs, read, lambda s, d: None, [], lambda: {"acme/w": "origin"})
    check("`repo view` is asked once per repository in one snapshot", sum(1 for c in calls if c[0] == "repo") == 1 and sum(1 for c in calls if c[0] == "view") == 4, calls)
    now = [0.0]
    reads: list[list[str]] = []
    cache = ls_data.LandedCache(ttl=60.0, clock=lambda: now[0], landed=lambda rows: reads.append([n for n, _ in rows]) or [f"  {n}  landed: no" for n, _ in rows])
    first = cache.lines(pairs)
    now[0] = 30.0
    cache.lines(pairs)
    check("inside the TTL the cached lines are reused, in order", len(reads) == 1 and first == [f"  d{i}  landed: no" for i in range(4)], reads)
    now[0] = 61.0
    cache.lines(pairs[:2])
    check("past the TTL only the stale tasks are read again", len(reads) == 2 and reads[1] == ["d0", "d1"], reads)


def loop(tmp: Path) -> None:
    import ls_data
    events: list[str] = []
    code = ls_data.watch(lambda: events.append("render"), interval=2.5, sleep=lambda s: events.append(f"sleep {s}"),
                         clear=lambda: events.append("clear"), max_iterations=3)
    check("the loop renders into a buffer, clears only when it is ready, sleeps, and stops at max_iterations",
          events == ["render", "clear", "sleep 2.5", "render", "clear", "sleep 2.5", "render", "clear"] and code == 0, events)
    check("the default interval is 3 seconds", ls_data.DEFAULT_INTERVAL == 3.0)
    state = {"n": 0}

    def interrupted(_seconds: float) -> None:
        state["n"] += 1
        raise KeyboardInterrupt

    events.clear()
    code = ls_data.watch(lambda: events.append("render"), sleep=interrupted, clear=lambda: None)
    check("Ctrl-C during the wait ends the loop with exit 0", code == 0 and events == ["render"] and state["n"] == 1, (code, events))

    def raising() -> None:
        raise KeyboardInterrupt

    check("Ctrl-C during a render ends the loop with exit 0", ls_data.watch(raising, sleep=lambda s: None, clear=lambda: None) == 0)
    check("zero iterations draw nothing", ls_data.watch(lambda: events.append("x"), max_iterations=0, clear=lambda: events.append("c")) == 0
          and "x" not in events)


def command_line(tmp: Path) -> None:
    tasks = make_tasks(tmp)
    before = digest(tasks)
    cli = [sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks)]
    child = subprocess.Popen([*cli, "--watch", "--interval", "0.2"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.5)
    child.send_signal(signal.SIGINT)
    try:
        out, err = child.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        out, err = child.communicate()
        check("crew ls --watch exits on SIGINT", False, "timed out")
        return
    check("Ctrl-C exits 0 with no traceback", child.returncode == 0 and "Traceback" not in err, (child.returncode, err))
    check("it clears the screen before each draw", out.count("\x1b[2J\x1b[H") >= 2, out.count("\x1b[2J\x1b[H"))
    check("it re-renders the existing table", "STATE" in out and "building" in out and "BLOCKED: waiting" in out, out[:300])
    check("it is read-only", digest(tasks) == before)
    plain = subprocess.run(cli, capture_output=True, text=True)
    check("without --watch nothing is cleared", "\x1b[2J" not in plain.stdout and "building" in plain.stdout, plain.stdout)
    missing = subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--cost", "--tasks-dir", str(tmp / "nowhere")],
                             capture_output=True, text=True, timeout=20)
    check("--cost with no tasks directory prints the error on stderr, exit 2",
          missing.returncode == 2 and missing.stdout == "" and "no tasks directory" in missing.stderr, (missing.returncode, missing.stdout, missing.stderr))
    for bad in (["--watch", "--interval", "0"], ["--watch", "--json"], ["--interval", "5"]):
        run = subprocess.run([*cli, *bad], capture_output=True, text=True, timeout=20)
        check(f"{' '.join(bad)} is refused", run.returncode == 2, (run.returncode, run.stderr))


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        gathering(tmp / "gather")
        limit_and_cache(tmp / "limit")
        loop(tmp / "loop")
        command_line(tmp / "cli")
    for name in FAILED:
        print(f"failed: {name}", file=sys.stderr)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
