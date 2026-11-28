"""Hook cost per benign shell command: the CPU the Claude Code `PreToolUse` Bash hooks take, and how many hook processes
Cursor starts (its own `beforeShellExecution` entries plus the Claude-format `PreToolUse` Bash ones it also runs).

Usage: uv run python scripts/dev/bench_hooks.py [--home DIR] [--runs N] [--command CMD]
DIR holds the installed `.claude/settings.json` and `.cursor/hooks.json` (default: $HOME). Each Claude hook command runs
under `bash -c` with the command's payload on stdin, as the harness runs it. Prints the median CPU and the Cursor count;
exits 1 above 120 ms or 3 processes (the hooks-diet targets).
"""

from __future__ import annotations

import argparse
import json
import re
import resource
import statistics
import subprocess
import sys
from pathlib import Path

CPU_MS, PROCESSES = 120.0, 3


def commands(path: Path, event: str, nested: bool) -> list[str]:
    """The hook commands `path` registers for `event` whose matcher covers a shell command (Bash or Shell)."""
    entries = json.loads(path.read_text(encoding="utf-8")).get("hooks", {}).get(event, []) if path.is_file() else []
    covers = [entry for entry in entries if re.fullmatch(entry.get("matcher") or ".*", "Bash") or re.fullmatch(entry.get("matcher") or ".*", "Shell")]
    return [hook["command"] for entry in covers for hook in (entry.get("hooks", []) if nested else [entry])]


def cpu_ms(hooks: list[str], payload: str, cwd: str) -> float:
    """User plus system CPU of one run of every hook, in milliseconds."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    for hook in hooks:
        subprocess.run(["bash", "-c", hook], input=payload, capture_output=True, text=True, cwd=cwd, check=False)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (after.ru_utime - before.ru_utime + after.ru_stime - before.ru_stime) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description="Hook CPU per benign Bash call, and Cursor hook processes per shell command.")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--runs", type=int, default=11)
    parser.add_argument("--command", default="git status")
    args = parser.parse_args()
    claude = commands(args.home / ".claude" / "settings.json", "PreToolUse", True)
    cursor = commands(args.home / ".cursor" / "hooks.json", "beforeShellExecution", False) + commands(args.home / ".cursor" / "hooks.json", "preToolUse", False)
    cwd = str(Path.cwd())
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": args.command}, "cwd": cwd})
    median = statistics.median(cpu_ms(claude, payload, cwd) for _ in range(args.runs))
    processes = len(cursor) + len(claude)
    print(f"Claude Code: {len(claude)} PreToolUse Bash hooks, median CPU {median:.0f} ms per call (target {CPU_MS:.0f})")
    print(f"Cursor: {processes} hook processes per shell command ({len(cursor)} Cursor entries, {len(claude)} Claude-format copies; target {PROCESSES})")
    return 1 if median > CPU_MS or processes > PROCESSES else 0


if __name__ == "__main__":
    sys.exit(main())
