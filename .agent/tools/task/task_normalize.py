"""The one-shot migration that puts every stored `## Status` value in its canonical spelling.

The store held `done` (24 tasks) and `DONE` (4) for one state, because a writer once emitted the
lowercase form. The reader normalizes now, so nothing is invisible; this migration fixes the files
so a person reading a spec sees the contract's token rather than a legacy one. It rewrites only the
token, keeps any suffix verbatim, and reports each file it touches — a second run finds nothing,
which is what makes it safe to run from a session-start hook or by hand.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.files import atomic_write  # noqa: E402
from task_status import STATUS, StatusError, canonical, read_status  # noqa: E402


def rewritten(path: Path) -> str:
    """The SPEC.md text with a canonical status, or "" when the file needs no change.

    Returns "" for an unreadable file, an unset status, an already-canonical value, and an unknown
    token: a migration reports what it cannot fix rather than guessing a state for it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = STATUS.search(text)
    if not match:
        return ""
    value = match.group(2).strip()
    try:
        if canonical(value) == value:
            return ""
    except StatusError:
        return ""
    return STATUS.sub(lambda m: m.group(1) + canonical(m.group(2).strip()), text, count=1)


def unknown_status(path: Path) -> str:
    """The status value of a spec that cannot be normalized because its token is not in the set."""
    value = read_status(path)
    if not value:
        return ""
    try:
        canonical(value)
    except StatusError as error:
        return str(error)
    return ""


def normalize_all(tasks_dir: Path, apply: bool, out=None) -> int:
    """Report, and with `apply` rewrite, every spec whose status is not canonical.

    The return value counts the files changed (or, in a dry run, would change), so a caller can
    assert idempotence: the second run returns 0 and prints the same "already canonical" summary.
    """
    sink = out or sys.stdout
    changed = 0
    failed = 0
    specs = sorted(tasks_dir.glob("*/SPEC.md"))
    for spec in specs:
        problem = unknown_status(spec)
        if problem:
            print(f"skip: {spec.parent.name}: {problem}", file=sys.stderr)
            continue
        updated = rewritten(spec)
        if not updated:
            continue
        before = read_status(spec) or ""
        if apply:
            try:
                atomic_write(spec, updated)
            except OSError as error:
                failed += 1
                print(f"error: {spec}: {error}", file=sys.stderr)
                continue
        changed += 1
        print(f"{'normalized' if apply else 'would normalize'}: {spec}: "
              f"{before} -> {canonical(before)}", file=sink)
    verb = "normalized" if apply else "would normalize"
    print(f"{verb} {changed} of {len(specs)} spec(s)" + ("" if changed else ": already canonical"),
          file=sink)
    if failed:
        print(f"error: {failed} spec(s) not written", file=sys.stderr)
        return -1
    return changed
