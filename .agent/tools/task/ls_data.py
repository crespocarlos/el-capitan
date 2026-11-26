"""What `crew ls` shows, gathered once, and the loop that keeps showing it.

`gather` is the only place the listing's data is collected (the task rows, the BLOCKED lines of open
tasks, the `landed` lines of done ones), so `crew-ls.py` and any later non-agentic TUI import the same
thing and cannot drift. It never writes. `watch` is the `--watch` loop: clear, render, sleep, repeat,
until Ctrl-C; the sleep, the clear and an iteration cap are parameters, so a test drives it without a
terminal or a clock.
"""
from __future__ import annotations

import contextlib
import io
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ls_landed import landed_lines
from task_lock import blocked_lines
from task_state import TaskState, head, load, name

DEFAULT_INTERVAL = 3.0
CLEAR = "\033[2J\033[H"
LandedReader = Callable[["list[tuple[str, Path]]"], "list[str]"]


@dataclass
class Snapshot:
    """The listing's data at one moment: rows, BLOCKED lines, and `landed` lines for DONE tasks."""

    rows: list[TaskState] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    landed: list[str] = field(default_factory=list)


def load_rows(tasks_dir: Path) -> list[TaskState]:
    """Every task directory that has a SPEC.md; a malformed one is skipped with a warning."""
    rows = []
    for task in sorted(tasks_dir.glob("*")):
        if not (task / "SPEC.md").exists():
            continue
        try:
            rows.append(load(task))
        except (OSError, ValueError, AttributeError) as error:
            print(f"warning: skipping {task.name}: {error}", file=sys.stderr)
    return rows


def shown_done(rows: list[TaskState], limit: int | None) -> list[TaskState]:
    """The DONE rows the table will show: open rows come first and count against `--limit`, done ones by age."""
    done = sorted((r for r in rows if head(r) == "DONE"), key=lambda r: r.age)
    return done if limit is None else done[:max(0, limit - sum(1 for r in rows if head(r) != "DONE"))]


def snapshot(rows: list[TaskState], show_done: bool, landed: LandedReader = landed_lines,
             limit: int | None = None) -> Snapshot:
    """The BLOCKED and `landed` lines for already-loaded rows; `landed` reads GitHub, so only when asked.

    `limit` (`--limit`) is applied first: only the DONE rows the table shows are read.
    """
    done = [(name(r), r.task) for r in shown_done(rows, limit)]
    return Snapshot(rows=rows, blocked=blocked_lines([(name(r), r.task) for r in rows if head(r) != "DONE"]),
                    landed=landed(done) if show_done and done else [])


def gather(tasks_dir: Path, show_done: bool = False, landed: LandedReader = landed_lines,
           limit: int | None = None) -> Snapshot:
    """Load the rows under `tasks_dir` and everything the listing derives from them."""
    return snapshot(load_rows(tasks_dir), show_done, landed, limit)


class LandedCache:
    """`landed` lines kept per task for `ttl` seconds, so a `--watch --all` loop reads GitHub once a minute."""

    def __init__(self, ttl: float = 60.0, clock: Callable[[], float] = time.monotonic,
                 landed: LandedReader = landed_lines) -> None:
        self.ttl, self.clock, self.landed = ttl, clock, landed
        self.kept: dict[str, tuple[float, str]] = {}

    def lines(self, rows: "list[tuple[str, Path]]") -> list[str]:
        now = self.clock()
        stale = [(n, t) for n, t in rows if str(t) not in self.kept or now - self.kept[str(t)][0] >= self.ttl]
        for (_, t), line in zip(stale, self.landed(stale) if stale else []):
            self.kept[str(t)] = (now, line)
        return [self.kept[str(t)][1] for _, t in rows if str(t) in self.kept]


def clear_screen() -> None:
    sys.stdout.write(CLEAR)
    sys.stdout.flush()


def watch(render: Callable[[], None], interval: float = DEFAULT_INTERVAL, sleep: Callable[[float], None] = time.sleep,
          clear: Callable[[], None] = clear_screen, max_iterations: int | None = None) -> int:
    """Render into a buffer, then clear and print it, every `interval` seconds; Ctrl-C ends it with 0.

    The screen is cleared only when the next frame is ready, so a slow read never leaves it blank.
    `max_iterations` caps the draws.
    """
    drawn = 0
    try:
        while max_iterations is None or drawn < max_iterations:
            frame = io.StringIO()
            with contextlib.redirect_stdout(frame):
                render()
            clear()
            sys.stdout.write(frame.getvalue())
            sys.stdout.flush()
            drawn += 1
            if max_iterations is not None and drawn >= max_iterations:
                break
            sleep(interval)
    except KeyboardInterrupt:
        return 0
    return 0
