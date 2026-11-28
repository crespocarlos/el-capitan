"""Send a harness's hook payload through `crew-hook.py`, as the harness does, in a throwaway HOME.

The harness is read from the payload's event name (PascalCase: claude-code, camelCase: cursor) unless given. The HOME
gets `~/.agent/hooks` linked to this checkout's rules, as install links it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"


def harness_of(payload: dict) -> str:
    return "cursor" if str(payload.get("hook_event_name") or "")[:1].islower() else "claude-code"


def command(home: Path, payload: dict, harness: str | None = None) -> list[str]:
    link = home / ".agent" / "hooks"
    if not link.is_symlink():
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(HOOKS)
    return [sys.executable, "-m", "crew.harness.crew_hook", harness or harness_of(payload), str(payload.get("hook_event_name") or "")]


def run(home: Path, payload: dict, harness: str | None = None, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command(home, payload, harness), input=json.dumps(payload), capture_output=True, text=True,
                          env={**os.environ, "HOME": str(home), **(env or {})}, cwd=cwd, timeout=120)
