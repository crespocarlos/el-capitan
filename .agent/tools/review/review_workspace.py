"""Where a review writes its artifacts: the task directory when writable, `/tmp` otherwise.

The pipeline used to choose `/tmp` only when no task was resolved. That condition never fires in a
sandbox that resolves the task but denies the write, so the documented primary path failed with
`Operation not permitted` and the review had nowhere to put its packages. Deciding by trying the
write removes the guess: the command creates the directory it is about to use and prints the path
that worked, so a caller never has to retry or fall back itself.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _try(path: Path) -> Path | None:
    """The directory when it can be created and written, else None."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        return None
    return path


def review_dir(task_dir: str | None, repo: str | None = None, mode: str = "self") -> Path:
    """Create and return the review directory for this run.

    A PR review always uses the temp form, because it must not depend on a task directory at all.
    Everything else prefers the task directory and falls back to a temp path that names the
    repository, so two reviews of different repos cannot collide.
    """
    stamp = _timestamp()
    if mode != "pr" and task_dir:
        chosen = _try(Path(task_dir) / "review" / stamp)
        if chosen is not None:
            return chosen
    name = repo or "review"
    base = Path(tempfile.gettempdir()) / f"crew-review-{name}" / "review"
    chosen = _try(base / stamp)
    if chosen is None:
        raise OSError(f"no writable review directory: tried {base / stamp}")
    return chosen


def report(path: Path, task_dir: str | None) -> int:
    """Print the chosen path, and say so on stderr when it is not the task directory.

    The fallback is not an error, but a silent switch would hide why a later `crew commit` cannot
    find the review, so the reason goes to stderr where it stays out of a `$(...)` capture.
    """
    print(path)
    if task_dir and str(path).startswith(str(task_dir)):
        return 0
    reason = "PR review uses a temp directory" if task_dir is None or task_dir == "" else (
        f"{task_dir} is not writable in this sandbox")
    print(f"review-dir: using {path} ({reason})", file=sys.stderr)
    return 0


def cleanup_stale(base: Path, keep: Path, limit: int = 10) -> list[Path]:
    """Remove older sibling review directories beyond `limit`, newest kept.

    A temp fallback accumulates one directory per review and nothing else prunes them; the task
    path does not need this because it lives with the task that will be committed or discarded.
    """
    removed: list[Path] = []
    if not base.is_dir():
        return removed
    siblings = sorted((p for p in base.iterdir() if p.is_dir() and p != keep), reverse=True)
    for stale in siblings[limit:]:
        for child in stale.rglob("*"):
            if child.is_file():
                try:
                    child.unlink()
                except OSError:
                    break
        try:
            os.removedirs(stale)
        except OSError:
            continue
        removed.append(stale)
    return removed
