#!/usr/bin/env python3
"""A test cannot hang unnoticed: `evals/test.sh` loads pytest-timeout, which fails a test that runs past its limit.

The sleeping test is written into this test's own temporary directory, so only this test ever runs it. A loop that
waits on a closed pipe is crew-lint's `pipe-read-eof`.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLEEPER = "import time\n\n\ndef test_sleeps() -> None:\n    time.sleep(30)\n"


def test_a_sleeping_test_fails_within_the_timeout(tmp: Path) -> None:
    """The runner fails a test that sleeps past the limit (shortened here to 2 s), well before it would wake."""
    sleeper = tmp / "sleeping.py"
    sleeper.write_text(SLEEPER, encoding="utf-8")
    start = time.monotonic()
    done = subprocess.run(["bash", str(ROOT / "evals" / "test.sh"), str(sleeper), "--timeout", "2"],
                          capture_output=True, text=True, timeout=45, env={**os.environ, "PYTEST_ADDOPTS": ""})
    elapsed = time.monotonic() - start
    assert done.returncode == 1 and "Timeout" in done.stdout and elapsed < 30, \
        (done.returncode, elapsed, done.stdout[-600:], done.stderr[-600:])
