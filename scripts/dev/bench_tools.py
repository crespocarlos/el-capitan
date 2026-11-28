"""The agent tools' speed and size budgets: `repo-facts --field branch` through the CLI (median, at most 70 ms) and
`task-list`'s default output for 30 tasks (at most 4 KB).

Usage: uv run python scripts/dev/bench_tools.py [--bin DIR] [--runs N]   (run inside a git checkout)
Exits 1 when a budget is exceeded. The 30 tasks are written to a throwaway HOME, never ~/.agent.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FIELD_MS, LIST_BYTES = 70.0, 4096


def field_ms(tool: Path, runs: int) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run([str(tool), "repo-facts", "--field", "branch"], capture_output=True, check=True)
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def list_bytes(tool: Path) -> int:
    with tempfile.TemporaryDirectory() as home:
        tasks = Path(home) / ".agent" / "tasks"
        for n in range(30):
            task = tasks / f"{n:08X}-0000-4000-8000-000000000000"
            task.mkdir(parents=True)
            (task / "SPEC.md").write_text(f"# Spec: task {n}\n\n## Status\nIMPLEMENTING\n\n- [ ] a\n- [x] b\n", encoding="utf-8")
            meta = {"slug": f"a-fairly-long-task-slug-number-{n}", "repo_remote_url": "git@github.com:owner/repository.git", "branch": f"feat/{n}"}
            (task / ".task-id").write_text(json.dumps(meta), encoding="utf-8")
        done = subprocess.run([str(tool), "task-list", "--repo", "all"], capture_output=True, check=True, env={"HOME": home, "PATH": ""})
        return len(done.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="The agent tools' speed and size budgets.")
    parser.add_argument("--bin", type=Path, default=Path(sys.executable).parent)
    parser.add_argument("--runs", type=int, default=11)
    args = parser.parse_args()
    tool = args.bin / "crew-tool.py"
    ms, size = field_ms(tool, args.runs), list_bytes(tool)
    print(f"repo-facts --field branch  {ms:6.1f} ms (budget {FIELD_MS:.0f})\ntask-list, 30 tasks        {size:6d} bytes (budget {LIST_BYTES})")
    return 1 if ms > FIELD_MS or size > LIST_BYTES else 0


if __name__ == "__main__":
    sys.exit(main())
