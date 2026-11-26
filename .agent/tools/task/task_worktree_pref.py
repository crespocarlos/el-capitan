"""`crew-progress.py worktree`: where the worker runs, and the one-time answer to the question.

el-capitan is project-agnostic, so the worker branches off the default branch in the CURRENT checkout
and a worktree is opt-in. The choice comes from, in order:

    1. the repo's `AGENTS.md`: `worktree: true` (a worktree) or `worktree: false` (here)
    2. a recorded answer: the marker `<git common dir>/crew-worktree` holding `worktree` or `here`
    3. nothing yet: `ask`, and the skill asks ONCE and records the answer

A user who asks for a worktree in so many words does not need this: the skill follows the request.
`record` writes the marker (shared by every worktree of the repo, never tracked) and one `WORKTREE:`
line in the task's PROGRESS.md; a repo that already has an answer keeps it (asked at most once).

    crew-progress.py worktree pref [--repo R] [--json]        prints worktree | here | ask
    crew-progress.py worktree record <worktree|here> <TASK_DIR> [--repo R]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from lib.files import atomic_write
from lib.git import GitError, output, toplevel

SETTING = re.compile(r"^worktree:[ \t]*(true|false)[ \t]*$", re.M | re.I)
CHOICES = ("worktree", "here")
MARKER = "crew-worktree"


def marker_path(root: Path) -> Path:
    """The per-repo marker, under git's common directory so every worktree of the repo shares it."""
    common = output(root, ["rev-parse", "--git-common-dir"]).strip()
    return (root / common).resolve() / MARKER


def agents_choice(root: Path) -> str:
    try:
        found = SETTING.search((root / "AGENTS.md").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    return "" if not found else ("worktree" if found.group(1).lower() == "true" else "here")


def recorded_choice(root: Path) -> str:
    try:
        value = marker_path(root).read_text(encoding="utf-8").strip()
    except (OSError, GitError):
        return ""
    return value if value in CHOICES else ""


def choose(root: Path) -> tuple[str, str]:
    """`(choice, source)`: `worktree`, `here` or `ask`, and where it came from."""
    for source, read in (("agents", agents_choice), ("recorded", recorded_choice)):
        value = read(root)
        if value:
            return value, source
    return "ask", "none"


def record(root: Path, choice: str, task_dir: Path) -> str:
    """Write the marker and the PROGRESS.md line once; returns the choice that stands."""
    standing = recorded_choice(root)
    if standing:
        return standing
    marker = marker_path(root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(marker, choice + "\n")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (task_dir / "PROGRESS.md").open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] WORKTREE: {choice} (asked once; recorded in {marker})\n")
    return choice


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="crew-progress.py worktree", description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("pref", "record"))
    parser.add_argument("rest", nargs="*", help="record: <worktree|here> <TASK_DIR>")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = toplevel(args.repo)
    except GitError as error:
        print(f"worktree: {error}", file=sys.stderr)
        return 2
    if args.action == "pref":
        choice, source = choose(root)
        print(json.dumps({"choice": choice, "source": source}, indent=2) if args.json else choice)
        return 0
    if len(args.rest) != 2 or args.rest[0] not in CHOICES or not Path(args.rest[1]).is_dir():
        print("worktree: record needs <worktree|here> <TASK_DIR>", file=sys.stderr)
        return 2
    print(record(root, args.rest[0], Path(args.rest[1])))
    return 0
