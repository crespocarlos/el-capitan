#!/usr/bin/env python3
"""Checks for the `## Status` contract: one token per state, and a migration that settles.

The store held `done` (24 tasks) and `DONE` (4) for the same finished state. Nothing normalized on
read, so a query that expected the contract's token saw half the finished work, and a writer that
emitted the legacy spelling could reintroduce it at any time. These cases pin the reader, the
rejection of an unknown token, and the migration's idempotence.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / ".agent" / "tools" / "task"
CLI = TASK_TOOLS / "crew-ls.py"

sys.path.insert(0, str(TASK_TOOLS))

import task_normalize  # noqa: E402
import task_status  # noqa: E402

FAILED: list[str] = []
STATES = ("DRAFTING", "APPROVED", "IMPLEMENTING", "ON-HOLD", "DONE")


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + str(detail) if detail else ''}")


def spec_text(value: str) -> str:
    return f"# Probe\n\n## Status\n{value}\n\n- [x] one\n"


def write_spec(directory: Path, value: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    spec = directory / "SPEC.md"
    spec.write_text(spec_text(value), encoding="utf-8")
    return spec


def matrix_cases(base: Path) -> None:
    """Every spelling of one state reads as the one contract token."""
    spellings = ("done", "Done", "DONE", "DONE ", "DONE\n", "done (PR opened: url)", "DONE.")
    tokens = set()
    for index, value in enumerate(spellings):
        spec = write_spec(base / f"matrix-{index}", value)
        tokens.add(task_status.head(task_status.read_status(spec)))
    check("every spelling of done normalizes to one token", tokens == {"DONE"}, tokens)
    spaced = write_spec(base / "spaced", "  IMPLEMENTING  ")
    check("surrounding whitespace is not a state",
          task_status.head(task_status.read_status(spaced)) == "IMPLEMENTING",
          task_status.read_status(spaced))


def canonical_states(base: Path) -> None:
    """Each contract state survives a round trip; a suffixed status keeps its suffix."""
    seen = set()
    for index, state in enumerate(STATES):
        spec = write_spec(base / f"state-{index}", state)
        value = task_status.read_status(spec)
        seen.add(task_status.token(value))
        check(f"{state} is unchanged by canonicalization",
              task_status.canonical(value) == state, task_status.canonical(value))
    check("the states round trip to themselves", seen == set(STATES), seen)
    suffixed = "ON-HOLD (auto-hold: no activity 14d; was APPROVED)"
    check("a suffixed status keeps its suffix", task_status.canonical(suffixed) == suffixed,
          task_status.canonical(suffixed))


def unknown_token(base: Path) -> None:
    """An unknown token is rejected, and the message names every allowed state."""
    spec = write_spec(base / "unknown", "SHIPPED")
    try:
        task_status.token(task_status.read_status(spec))
    except task_status.StatusError as error:
        message = str(error)
        missing = [state for state in STATES if state not in message]
        check("an unknown token is rejected", True)
        check("the rejection names the allowed set", not missing, missing)
    else:
        check("an unknown token is rejected", False, "no StatusError")


def cli_rejects_unknown(base: Path) -> None:
    """The command reports the unknown status on stderr and exits 2, naming the allowed set."""
    spec = write_spec(base / "cli-unknown", "SHIPPED")
    result = subprocess.run([sys.executable, str(CLI), "--status-file", str(spec)],
                            capture_output=True, text=True)
    check("--status-file still prints a value for a malformed status", result.stdout.strip()
          == "SHIPPED", (result.returncode, result.stdout, result.stderr))
    check("a malformed status exits 2 and names the allowed set",
          result.returncode == 2 and "DRAFTING" in result.stderr and "DONE" in result.stderr,
          (result.returncode, result.stderr))
    result = subprocess.run([sys.executable, str(CLI), "--normalize-status",
                             "--tasks-dir", str(base)], capture_output=True, text=True)
    check("the migration skips an unknown token", "skip:" in result.stderr and "SHIPPED" in
          result.stderr, result.stderr)


def migration_cases(base: Path) -> None:
    """The migration rewrites each legacy file once, then reports nothing left to change."""
    tasks = base / "store"
    write_spec(tasks / "legacy-one", "done")
    write_spec(tasks / "legacy-two", "done (PR opened: https://example.test/pr/1)")
    write_spec(tasks / "canonical", "DONE")
    write_spec(tasks / "open", "IMPLEMENTING")
    preview = io.StringIO()
    would_change = task_normalize.normalize_all(tasks, False, out=preview)
    check("a dry run reports every legacy spec", would_change == 2, would_change)
    check("a dry run writes nothing",
          task_status.read_status(tasks / "legacy-one" / "SPEC.md") == "done")
    applied = io.StringIO()
    check("the applied run changes the same files",
          task_normalize.normalize_all(tasks, True, out=applied) == 2, applied.getvalue())
    check("the legacy token is rewritten",
          task_status.read_status(tasks / "legacy-one" / "SPEC.md") == "DONE")
    check("a suffixed legacy token keeps its suffix",
          task_status.read_status(tasks / "legacy-two" / "SPEC.md")
          == "DONE (PR opened: https://example.test/pr/1)",
          task_status.read_status(tasks / "legacy-two" / "SPEC.md"))
    check("an open status is untouched",
          task_status.read_status(tasks / "open" / "SPEC.md") == "IMPLEMENTING")
    second = io.StringIO()
    check("a second run changes nothing", task_normalize.normalize_all(tasks, True, out=second) == 0,
          second.getvalue())
    check("the second run says so", "already canonical" in second.getvalue(), second.getvalue())


def listing_hides_nothing(base: Path) -> None:
    """The listing counts a legacy `done` spec as done, which is what was invisible before."""
    tasks = base / "listing"
    write_spec(tasks / "legacy", "done")
    write_spec(tasks / "canonical", "DONE")
    result = subprocess.run([sys.executable, str(CLI), "--tasks-dir", str(tasks)],
                            capture_output=True, text=True)
    check("the listing counts both spellings as done", "2 done" in result.stdout, result.stdout)


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="crew-status-"))
    try:
        matrix_cases(base)
        canonical_states(base)
        unknown_token(base)
        cli_rejects_unknown(base)
        migration_cases(base)
        listing_hides_nothing(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("all status-contract checks passed" if not FAILED else f"status: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
