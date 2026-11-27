#!/usr/bin/env python3
"""Where the helper checkout lives, and whether the two halves of a run's evidence agree.

`resolve_root` names the checkout the running server serves (override, LaunchAgent
`WorkingDirectory`, default path). The rest check the remote, the build, the dev-stack script and
the ports. Kibana-specific by design, like the whole nightshift tool (its ports and paths are Kibana's).
"""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import socket
import subprocess
from pathlib import Path

from lib.git import GitError, commit_time, remote_url, remotes, slug_from_url

CANONICAL_REMOTE = "elastic/nightshift-pr-helper"
# `data/logs/<label suffix>.log` holds both streams; launchd.sh writes `web.log`/`sync.log`.
LOG_TAIL_LINES = 15
PORTS_TO_CHECK = (5601, 9200)


def default_dir() -> Path:
    """Read at call time, so a HOME set for one call is the HOME it uses."""
    return Path("~/Documents/dev/nightshift-pr-helper").expanduser()


def plist_working_directory() -> tuple[Path | None, str]:
    """The checkout the running server serves, which can differ from the default path."""
    plist = Path("~/Library/LaunchAgents/dev.prhelper.web.plist").expanduser()
    if not plist.is_file():
        return None, f"{plist} is missing (npm run launchd:install)"
    try:
        with plist.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        return None, f"cannot read {plist}: {error}"
    root = payload.get("WorkingDirectory")
    if not root:
        return None, f"{plist} has no WorkingDirectory"
    return Path(root).expanduser(), ""


def resolve_root() -> tuple[Path, str]:
    """Prefer an explicit override, then the server's own directory, then the default."""
    override = os.environ.get("NIGHTSHIFT_PR_HELPER_DIR", "").strip()
    if override:
        return Path(override).expanduser(), "NIGHTSHIFT_PR_HELPER_DIR"
    from_plist, _ = plist_working_directory()
    if from_plist is not None and from_plist.is_dir():
        return from_plist, "LaunchAgent WorkingDirectory"
    return default_dir(), "default path"


def is_canonical_remote(url: str) -> bool:
    """Exact owner/repo match, because the config loader later executes code from this checkout.

    A suffix match would accept `evilelastic/nightshift-pr-helper`, which is a different repository
    and would run its code.
    """
    return slug_from_url(url) == CANONICAL_REMOTE


def elastic_remote(root: Path) -> tuple[str, str]:
    """The canonical repo, under either remote name, so a clone named `origin` still passes."""
    try:
        names = remotes(root)
    except GitError:
        return "", "not a git checkout"
    for name in names:
        try:
            url = remote_url(root, name)
        except GitError:
            continue
        if url and is_canonical_remote(url):
            return name, ""
    return "", f"no remote points at {CANONICAL_REMOTE}"


def build_is_fresh(root: Path) -> tuple[bool, str]:
    """A server serving an older build than HEAD runs code nobody reviewed."""
    build_id = root / ".next" / "BUILD_ID"
    try:
        head = commit_time(root)
    except GitError:
        head = None
    if not build_id.is_file():
        return False, "no build; run npm run launchd:restart-web"
    if head is None:
        return True, ""
    if build_id.stat().st_mtime < head:
        return False, "build is older than HEAD; run npm run launchd:restart-web"
    return True, ""


def launchd_state() -> tuple[bool, str]:
    """macOS-only: a checkout can be usable while the server is not installed at all."""
    if not shutil.which("launchctl"):
        return True, "launchctl unavailable; skipping the LaunchAgent check"
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    label = f"gui/{uid}/dev.prhelper.web"
    result = subprocess.run(["launchctl", "print", label], capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""
    log = default_dir() / "data" / "logs" / "web.log"
    tail = ""
    if log.is_file():
        lines = log.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:]
        tail = "\n".join(lines)
    detail = f"{label} is not loaded; run npm run launchd:install"
    return False, f"{detail}\n{tail}" if tail else detail


def dev_stack_current(root: Path, stack: str | None) -> tuple[bool, str]:
    """Whether the installed dev_stack.sh honours the flag an e2e run needs.

    The installed script is a user-owned copy of `examples/kibana-dev-tools/dev_stack.sh`.
    Nightshift exports DEV_STACK_EIS=1 on every deploy because a stack without EIS has no chat
    model and e2e ends `blocked`; a copy that ignores the variable never wires EIS in.
    """
    example = root / "examples" / "kibana-dev-tools" / "dev_stack.sh"
    installed = Path(stack).expanduser() if stack else None
    if not installed or not installed.is_file() or not example.is_file():
        return True, ""
    if "DEV_STACK_EIS" in installed.read_text(errors="replace"):
        return True, ""
    if "DEV_STACK_EIS" not in example.read_text(errors="replace"):
        return True, ""
    return False, f"{installed} ignores DEV_STACK_EIS, so a deploy can start a stack with no LLM connector"


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def ports_status() -> tuple[bool, str]:
    """A note, not a hard gate: a worktree that already runs its own stack is the normal case.

    A deploy that lands on an already-bound port clashes with whatever is listening there (a prior
    stack, Scout, a local ES), so it is reported for the operator to judge.
    """
    busy = [str(port) for port in PORTS_TO_CHECK if port_in_use(port)]
    if not busy:
        return True, f"{', '.join(str(p) for p in PORTS_TO_CHECK)} are free"
    return False, f"port(s) {', '.join(busy)} already have a listener"


def duplicate_config_keys(path: Path) -> list[str]:
    """Keys a hand-edited config.local.json declares twice.

    JSON parsing silently keeps only the last one, so the duplicate never surfaces unless something
    scans the raw pairs before they collapse.
    """
    if not path.is_file():
        return []
    duplicates: list[str] = []

    def hook(pairs: list[tuple[str, object]]) -> dict:
        seen: dict[str, object] = {}
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen[key] = value
        return seen

    try:
        json.loads(path.read_text(errors="replace"), object_pairs_hook=hook)
    except (json.JSONDecodeError, OSError):
        return []
    return duplicates
