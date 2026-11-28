"""Start-up cost of the 8 most-used commands: the median wall time of `<command> --help`, each against a ceiling.

Usage: uv run python scripts/dev/bench_startup.py [--bin DIR] [--runs N] [--ceiling-ms MS]
DIR holds the launchers (default: this environment's, beside its python; `~/.agent/bin` measures an install).
Prints one median per command; exits 1 when any median exceeds the ceiling (60 ms).
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

# The commands the prompts call most often (count of `~/.agent/bin/<name>` references).
COMMANDS = tuple(f"crew-{name}.py" for name in ("task", "mem", "repo-info", "review-findings", "pr-actions", "task-context", "metric", "verify"))


def median_ms(launcher: Path, runs: int) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run([str(launcher), "--help"], capture_output=True, check=True)
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def main() -> int:
    parser = argparse.ArgumentParser(description="Median --help time of the 8 most-used commands.")
    parser.add_argument("--bin", type=Path, default=Path(sys.executable).parent)
    parser.add_argument("--runs", type=int, default=11)
    parser.add_argument("--ceiling-ms", type=float, default=60.0)
    args = parser.parse_args()
    medians = {name: median_ms(args.bin / name, args.runs) for name in COMMANDS}
    for name, ms in medians.items():
        print(f"{name:26} {ms:6.1f} ms{'  over the ceiling' if ms > args.ceiling_ms else ''}")
    print(f"median of medians {statistics.median(medians.values()):.1f} ms (ceiling {args.ceiling_ms:.0f} ms per command)")
    return 1 if any(ms > args.ceiling_ms for ms in medians.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
