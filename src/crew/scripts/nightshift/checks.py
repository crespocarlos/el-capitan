#!/usr/bin/env python3
"""The preflight probes, as one table: what blocks a run, and what is only a note.

A failing check in `location_checks` or `server_checks` stops the skill, because `crew e2e` starts
real runs; a note (a stack already on the port) describes a usable machine. `server_checks` also
returns the queue payload it read, so the caller does not ask twice.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from crew.lib.git import GitError, behind_count, current_branch, fetch_remote
from crew.scripts.nightshift.client import ApiError, Unreachable, agent_check, base_url, request
from crew.scripts.nightshift.location import (
    CANONICAL_REMOTE,
    build_is_fresh,
    dev_stack_current,
    duplicate_config_keys,
    elastic_remote,
    launchd_state,
    ports_status,
)


def check(name: str, ok: bool, detail: str, fix: str = "") -> dict:
    """One reported probe: its verdict, why, and the fix when it did not pass."""
    return {"check": name, "ok": ok, "detail": detail, "fix": fix if not ok else ""}


def helper_up_to_date(root: Path, remote: str) -> tuple[bool, str]:
    """Best-effort only: a fetch that cannot reach the network (offline, auth) must never block.

    Any error here is reported as unknown, not as a failing check. `gh` goes first because it
    carries the authentication; a machine where api.github.com is blocked answers through `git
    ls-remote` instead; a machine with neither reports unknown.
    """
    if not remote:
        return True, "no elastic remote to compare against"
    try:
        branch = current_branch(root)
    except GitError:
        return True, "detached HEAD; skipping"
    try:
        fetch_remote(root, remote, branch)
        count = behind_count(root, remote, branch)
    except GitError as error:
        return True, f"could not reach the remote to check; skipping ({error})"
    if count == 0:
        return True, f"up to date with {remote}/{branch}"
    return False, f"{count} commit(s) behind {remote}/{branch}"


def location_checks(root: Path, source: str) -> list[dict]:
    """The checks that need only the checkout path: its existence, its remote, and node_modules."""
    checks = [check("location", root.is_dir(), f"{root} ({source})", "set NIGHTSHIFT_PR_HELPER_DIR to a nightshift-pr-helper checkout")]
    if not root.is_dir():
        return checks
    remote, why = elastic_remote(root)
    checks.append(
        check(
            "repo",
            bool(remote),
            why or f"{remote} -> {CANONICAL_REMOTE}",
            f"add the canonical remote: git -C {root} remote add elastic https://github.com/{CANONICAL_REMOTE}",
        )
    )
    modules = root / "node_modules"
    checks.append(check("node_modules", modules.is_dir(), str(modules), f"cd {root} && npm install"))
    return checks


def machine_notes(root: Path, remote: str) -> list[dict]:
    """Notes about the checkout and the machine: freshness, config, ports, launchd, and build.

    None of these blocks a run. A server started with `npm run dev` answers and works, so gating on
    a LaunchAgent would reject a usable machine; they are reported so the operator can see them.
    """
    notes = []
    fresh, why = helper_up_to_date(root, remote)
    notes.append(check("helper_up_to_date", fresh, why, f"cd {root} && git pull {remote}"))
    dupes = duplicate_config_keys(root / "config.local.json")
    notes.append(
        check(
            "config_duplicate_keys",
            not dupes,
            f"duplicate key(s) in config.local.json: {', '.join(sorted(set(dupes)))}" if dupes else "no duplicate keys in config.local.json",
            "remove the duplicate key(s); the later one silently wins over the earlier one",
        )
    )
    free, why = ports_status()
    notes.append(check("ports_free", free, why, "a process already listens on that port; stop it, or pick a worktree that is not already using it"))
    running, why = launchd_state()
    notes.append(check("launchd", running, why or "dev.prhelper.web is loaded", f"cd {root} && npm run launchd:install"))
    # `.next/BUILD_ID` belongs to the launchd production server; a `npm run dev` server never
    # reads it, so its age says nothing and a restart would target a service that is not loaded.
    if running:
        fresh, why = build_is_fresh(root)
        notes.append(check("build_fresh", fresh, why or "build is newer than HEAD", f"cd {root} && npm run launchd:restart-web"))
    return notes


def server_checks(root: Path) -> tuple[list[dict], dict | None]:
    """The checks that need the HTTP API: reachability, a shaped queue, and an enabled machine.

    Returns the checks and the queue payload, or `None` when the server never answered a shaped
    response. The queue endpoint is the only read-only proof that the port answers nightshift and
    can report its machines; `/api/state` advances the queue.
    """
    fix = f"cd {root} && npm run dev   # or npm run launchd:install"
    restart = f"cd {root} && npm run launchd:restart-web"
    try:
        queue = request("GET", "/api/e2e/queue", timeout=15)
    except Unreachable as error:
        return [check("server", False, f"{base_url()} unreachable: {error}", fix)], None
    except ApiError as error:
        return [check("server", False, f"{base_url()} answered: {error}", restart)], None
    shaped = isinstance(queue.get("queued"), list) and isinstance(queue.get("machines"), list)
    checks = [check("server", shaped, f"{base_url()} /api/e2e/queue", restart)]
    machines = queue.get("machines") if shaped else []
    enabled = [m for m in machines if isinstance(m, dict) and m.get("enabled")]
    checks.append(
        check(
            "machine_enabled",
            bool(enabled),
            ", ".join(str(m.get("label") or m.get("id")) for m in enabled) or "no machine enabled",
            "enable a review machine at /e2e, or set e2e.machines in config.local.json",
        )
    )
    return checks, queue


def config_checks(root: Path) -> tuple[list[dict], list[dict]]:
    """The agent-config checks, split into blocking checks and notes, or `(None, None)` on failure."""
    cli = configured_cli(root)
    if cli is None:
        return [check("config", False, "could not load config through nightshift's loader", f"cd {root} && npm install")], []
    missing = [
        (name, path, flag)
        for name, path, flag in (
            ("kibana.repo", cli.get("kibana"), cli.get("kibanaExists")),
            ("nightshiftRepo", cli.get("nightshift"), cli.get("nightshiftExists")),
            ("kibana.devStackScript", cli.get("stack"), cli.get("stackExists")),
        )
        if not path or not flag
    ]
    checks = [
        check(
            "config_paths",
            not missing,
            ", ".join(f"{name}={path}" for name, path, _ in missing) or "all configured paths exist",
            f"fix in {root}/config.local.json: " + ", ".join(f"{name} ({path})" for name, path, _ in missing),
        )
    ]
    current, why = dev_stack_current(root, cli.get("stack"))
    notes = [
        check(
            "dev_stack_eis",
            current,
            why or "dev_stack.sh honors DEV_STACK_EIS",
            f"review `diff {cli.get('stack')} {root}/examples/kibana-dev-tools/dev_stack.sh`, back up the installed script, then copy the example over it",
        )
    ]
    checks.append(check("e2e_enabled", bool(cli.get("e2e")), "e2e.enabled is true", f"set e2e.enabled in {root}/config.json"))
    checks.append(check("config", True, f"agent.cli={cli.get('cli')}"))
    cli_name = str(cli.get("cli") or "")
    usable, why = agent_check(cli_name) if cli_name else (False, "agent.cli is not set")
    checks.append(
        check("agent_cli", usable, why or f"{cli_name} reports models", f"install and sign in to {cli_name}, or override agent.cli in {root}/config.local.json")
    )
    return checks, notes


def configured_cli(root: Path) -> dict | None:
    """Read the agent config through nightshift's own loader instead of re-implementing it.

    Loaded as a Node preload rather than through the `tsx` CLI: tsx's CLI opens a supervisor
    socket on a unix pipe, which a sandboxed shell denies. The loader is also where `~` and
    `config.local.json` are merged, so re-reading config.json here would report a different
    repo than the server uses.
    """
    node = shutil.which("node")
    if not node or not (root / "node_modules" / "tsx").is_dir():
        return None
    script = (
        "import('./lib/config.ts').then(m => {"
        "const fs = require('node:fs');"
        "const c = m.loadConfig();"
        "const ex = (p) => { try { return fs.existsSync(p); } catch { return false; } };"
        "console.log(JSON.stringify({cli: c.agent.cli, e2e: !!c.e2e?.enabled,"
        "kibana: c.kibana.repo, kibanaExists: ex(c.kibana.repo),"
        "nightshift: c.nightshiftRepo, nightshiftExists: ex(c.nightshiftRepo),"
        "stack: c.kibana.devStackScript, stackExists: ex(c.kibana.devStackScript)}));"
        "})"
    )
    result = subprocess.run([node, "--import", "tsx/esm", "--eval", script], capture_output=True, text=True, cwd=root)
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return None
