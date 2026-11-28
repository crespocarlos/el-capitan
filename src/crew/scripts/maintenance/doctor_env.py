"""The doctor's environment checks: the interpreter and the lock, the required tools, the state sizes."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from crew.core.task.task_gc import TELEMETRY_NOTICE, Places, size_of
from crew.lib.files import read_json_object
from crew.lib.git import GitError, gh, run_git
from crew.scripts.maintenance.doctor_checks import RERUN, ROOT, Line

REQUIRED = ("gh", "git", "jq", "uv")  # what install.sh's preflight requires


def version(argv: list[str]) -> str | None:
    """The version number `argv` prints ("present" when it prints none), or None when absent or failing."""
    if not shutil.which(argv[0]):
        return None
    try:
        if argv[0] == "git":
            done = run_git(None, argv[1:], check=False, timeout=10)
        elif argv[0] == "gh":
            done = gh(*argv[1:], timeout=10)
        else:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError, GitError):
        return None
    number = re.search(r"\d+(?:\.\d+)+", done.stdout or done.stderr or "")
    return (number.group(0) if number else "present") if done.returncode == 0 else None


def check_environment(home: Path, root: Path = ROOT) -> list[Line]:
    """The interpreter the tools run on; uv.lock against pyproject.toml, ~/.agent/venv against the lock (synced as install
    does), and the revision the venv was built from (the install manifest) against the checkout's HEAD."""
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(home / ".agent" / "venv")}
    checks = (
        (["lock", "--check"], "uv.lock is stale against pyproject.toml (uv lock)"),
        (["sync", "--frozen", "--no-dev", "--managed-python", "--no-editable", "--check"], f"~/.agent/venv differs from uv.lock{RERUN}"),
    )
    stale = [
        text
        for argv, text in checks
        if shutil.which("uv") is None or subprocess.run(["uv", *argv, "--offline", "--quiet", "--project", str(root)], env=env, capture_output=True).returncode
    ]
    try:
        installed = str((read_json_object(home / ".agent" / "install-manifest.json").get("venv") or {}).get("revision") or "")
    except ValueError:
        installed = ""
    head = run_git(root, ["rev-parse", "HEAD"], check=False).stdout.strip()
    behind = installed[:12] != head[:12]
    revision = f"installed {installed[:12] or 'unknown'}, checkout HEAD {head[:12] or 'unknown'}" + (RERUN if behind else "")
    python = f"python {'.'.join(map(str, sys.version_info[:3]))} ({sys.executable})"
    level = "FAIL" if stale else "WARN" if behind else "ok"
    return [Line(level, "python", f"{python}; " + ("; ".join(stale) or "venv matches uv.lock") + f"; {revision}")]


def check_tools(sign_in: bool = True) -> list[Line]:
    """gh, git, jq and uv (required); gitleaks (the credentials rule's scanner: without it commits and pushes are
    denied); shfmt (the hooks' parser, the venv's): without it the shell guards cannot judge a command; gh sign-in."""
    found = {name: version([name, "--version"]) for name in REQUIRED}
    missing = [name for name in REQUIRED if not found[name]]
    listed = ", ".join(f"{name} {found[name] or 'MISSING'}" for name in REQUIRED)
    fix = f"; install {', '.join(missing)} (install.sh's preflight lists what it needs)" if missing else ""
    lines = [Line("FAIL" if missing else "ok", "tools", listed + fix)]
    shfmt = version([shutil.which("shfmt") or str(Path.home() / ".agent" / "venv" / "bin" / "shfmt"), "--version"])
    lines.append(Line("ok", "tools", f"shfmt {shfmt}") if shfmt else Line("FAIL", "tools", f"shfmt absent: the shell guards cannot parse commands{RERUN}"))
    gitleaks = version([shutil.which("gitleaks") or str(Path.home() / ".agent" / "bin" / "gitleaks"), "version"])
    absent = f"gitleaks absent: the shell guard denies every commit and push{RERUN}"
    lines.append(Line("ok", "tools", f"gitleaks {gitleaks}") if gitleaks else Line("FAIL", "tools", absent))
    if found["gh"] and sign_in:
        try:
            signed_in = gh("auth", "status", timeout=20).returncode == 0
        except (OSError, subprocess.SubprocessError):
            signed_in = False
        lines.append(Line("ok", "gh", "signed in") if signed_in else Line("FAIL", "gh", "not signed in: run gh auth login"))
    return lines


def check_state(places: Places, limits: dict) -> list[Line]:
    """Task and session state against the `doctor` limits of ~/.agent/config.json, and the legacy telemetry."""
    lines = []
    for label, path, key in (("tasks", places.tasks, "tasks_mb"), ("sessions", places.memory / ".sessions", "sessions_mb")):
        size = size_of(path) / 1e6 if path.exists() else 0.0
        hint = "; crew gc lists what it would collect" if size > limits[key] else ""
        lines.append(Line("FAIL" if hint else "ok", "state", f"{label} {size:.1f} MB (limit {limits[key]} MB){hint}"))
    telemetry = places.agent / "telemetry"
    if telemetry.exists():
        size = size_of(telemetry) / 1e6
        text = f"~/.agent/telemetry {size:.1f} MB: {TELEMETRY_NOTICE}; crew-task.py gc --only telemetry --apply removes only it"
        lines.append(Line("FAIL", "state", text))
    return lines
