"""The detached half of `crew-progress.py verify`: `--background` launches, `--wait` reads the result.

A run has four states in its JSON: `starting` (written before the child exists, so a previous run's
`done` file can never answer this launch), `running`, `done` and `failed` (the child died before it
finished, with a `reason` and a pointer to `<out>.log`). Every payload records the child's `pid`.
`--wait` accepts only a `done` whose `started` is not older than the launch it waits for, and has no
total limit while that pid is alive; a pid that is gone with no `done` or `failed` payload is a failed
run (exit 2, the log named). Exit codes match the foreground path: 1 when a gate failed, 2 or 3 when
the result is NOT VERIFIED (nothing runnable, or the run itself failed); `--wait-timeout` that runs out
exits 4: still running, do not hand off.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lib.files import atomic_write
from task_verify_notes import partial_line

CLI = Path(__file__).resolve().parent / "crew-progress.py"
NO_PID_GRACE = 30  # seconds a payload may go without a recorded pid before --wait calls the run failed
STILL_RUNNING = 4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def gate_line(gate: dict) -> str:
    return f"{gate['name']} exit={gate['exit']}" + (" cached" if gate.get("cached") else "")


def print_lines(result: dict) -> None:
    for gate in result["gates"]:
        print(gate_line(gate))


def log_of(out: Path) -> Path:
    return out.with_suffix(".log")


def write_failed(out: Path | None, reason: str) -> None:
    """Mark a run that ended without a `done` result; the log beside `out` has the detail."""
    if out is None:
        return
    atomic_write(out, json.dumps({"schema_version": 1, "state": "failed", "verified": False, "started": now(), "pid": os.getpid(),
                                  "reason": reason, "log": str(log_of(out)), "gates": []}, indent=2) + "\n")


def read(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def background(argv: list[str], out: Path | None) -> int:
    if out is None:
        print("verify: --background needs --out or --task-dir", file=sys.stderr)
        return 2
    launched = now()
    out.parent.mkdir(parents=True, exist_ok=True)
    starting = {"schema_version": 1, "state": "starting", "started": launched, "gates": []}
    atomic_write(out, json.dumps(starting) + "\n")
    rest = [a for a in argv if a != "--background"]
    with log_of(out).open("w", encoding="utf-8") as handle:
        child = subprocess.Popen([sys.executable, str(CLI), "verify", *rest, "--out", str(out)],
                                 stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    if read(out).get("state") == "starting":  # the child's own payloads carry its pid too
        atomic_write(out, json.dumps({**starting, "pid": child.pid}) + "\n")
    print(f"started pid={child.pid} out={out} (wait: crew-progress.py verify --wait {out} --since {launched})")
    return 0


def fresh(result: dict, since: str | None) -> bool:
    try:
        return since is None or datetime.fromisoformat(str(result.get("started"))) >= datetime.fromisoformat(since)
    except ValueError:
        return False


def alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def answer(result: dict, since: str | None, path: Path) -> int | None:
    """The exit code a finished (`done` or `failed`) fresh result gives, or None while it is not finished."""
    if result.get("state") == "failed" and fresh(result, since):
        print(f"verify: NOT VERIFIED: the run failed: {result.get('reason')} (log: {log_of(path)})", file=sys.stderr)
        return 2
    if result.get("state") != "done" or not fresh(result, since):
        return None
    if result.get("partial") and result["gates"]:
        print(partial_line(result["skipped"]))
    print_lines(result)
    if result.get("verified", True):
        return 0 if all(g["exit"] == 0 for g in result["gates"]) else 1
    if not result["gates"]:
        print("verify: NOT VERIFIED: no gates declared (CI workflow, AGENTS.md gates block, .agent/gates.json). This is not a pass.")
    return int(result.get("verdict_exit", 3))


def wait(path: Path, wait_timeout: int | None, since: str | None = None) -> int:
    """Block until the run at `path` finishes, its child dies, or `wait_timeout` seconds pass (exit 4)."""
    started = time.monotonic()
    while wait_timeout is None or time.monotonic() - started < wait_timeout:
        result = read(path)
        code = answer(result, since, path)
        if code is not None:
            return code
        pid = result.get("pid")
        gone = not alive(pid) if pid is not None else time.monotonic() - started > NO_PID_GRACE
        if gone:
            code = answer(read(path), since, path)
            if code is not None:
                return code
            what = f"pid {pid} exited" if pid is not None else "no running verify is recorded"
            print(f"verify: NOT VERIFIED: the run failed: {what} without a result (log: {log_of(path)})", file=sys.stderr)
            return 2
        time.sleep(1)
    print(f"verify: {path} still running after {wait_timeout}s; do not hand off (log: {log_of(path)})", file=sys.stderr)
    return STILL_RUNNING
