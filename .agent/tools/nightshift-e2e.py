#!/usr/bin/env python3
"""Drive nightshift-pr-helper e2e runs through its local HTTP API.

Subcommands: `doctor` (read-only machine and server preflight), `worktrees`, `start`,
`status`, `report`, `followup`, `stop`, `stack-stop`. The server is `NIGHTSHIFT_URL`, default
`http://localhost:3737`; PR keys are nightshift's `owner__repo__number`.

Deliberately absent: the queue (`POST /api/e2e/queue`) and `post-comment`. A queued run
comments on the PR by default, which is external state the caller has to confirm, and a
direct start already reaches the same runner.

Exit codes: 0 ok, 1 request rejected or invalid output, 2 invalid invocation, 3 server
unreachable. Diagnostics for 1 come from nightshift's own `error` field, so its message
for an untracked PR or a disabled e2e reaches the user unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://localhost:3737"
DEFAULT_DIR = Path("~/Documents/dev/nightshift-pr-helper").expanduser()
PLIST = Path("~/Library/LaunchAgents/dev.prhelper.web.plist").expanduser()
CANONICAL_REMOTE = "elastic/nightshift-pr-helper"
UNREACHABLE = 3
KEY = re.compile(r"^[A-Za-z0-9._-]+__[A-Za-z0-9._-]+__\d+$")
# `data/logs/<label suffix>.log` holds both streams; launchd.sh writes `web.log`/`sync.log`.
LOG_TAIL_LINES = 15


def base_url() -> str:
    return (os.environ.get("NIGHTSHIFT_URL", "").strip() or DEFAULT_URL).rstrip("/")


def request(method: str, path: str, body: dict | None = None, timeout: float = 60.0) -> dict:
    url = base_url() + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    call = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(call, timeout=timeout) as response:
            try:
                payload = json.loads(response.read().decode() or "{}")
            except json.JSONDecodeError as error:
                raise ApiError(f"invalid JSON response from {url}") from error
            if not isinstance(payload, dict):
                raise ApiError(f"invalid JSON object response from {url}")
            return payload
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("error") if isinstance(parsed, dict) else detail
        except json.JSONDecodeError:
            message = detail or error.reason
        raise ApiError(str(message), status=error.code) from error
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        raise Unreachable(str(getattr(error, "reason", error))) from error


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Unreachable(RuntimeError):
    pass


def check_key(key: str) -> str:
    if not KEY.match(key):
        raise ValueError(f"{key!r} is not a nightshift PR key (expected owner__repo__number)")
    return key


def plist_working_directory() -> tuple[Path | None, str]:
    """The checkout the running server serves, which can differ from the default path."""
    if not PLIST.is_file():
        return None, f"{PLIST} is missing (npm run launchd:install)"
    try:
        with PLIST.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        return None, f"cannot read {PLIST}: {error}"
    root = payload.get("WorkingDirectory")
    if not root:
        return None, f"{PLIST} has no WorkingDirectory"
    return Path(root).expanduser(), ""


def resolve_root() -> tuple[Path | None, str]:
    """Prefer an explicit override, then the server's own directory, then the default."""
    override = os.environ.get("NIGHTSHIFT_PR_HELPER_DIR", "").strip()
    if override:
        return Path(override).expanduser(), "NIGHTSHIFT_PR_HELPER_DIR"
    from_plist, _ = plist_working_directory()
    if from_plist is not None and from_plist.is_dir():
        return from_plist, "LaunchAgent WorkingDirectory"
    return DEFAULT_DIR, "default path"


REMOTE_URL = re.compile(
    r"^(?:https?://[^/]+/|ssh://[^/]+/|[^/@\s]+@[^:/\s]+:)(?P<repo>[^/]+/[^/]+)$")


def is_canonical_remote(url: str) -> bool:
    """Exact owner/repo match. A suffix match accepts `evilelastic/...`, and the config
    loader later executes code from this checkout."""
    match = REMOTE_URL.match(url.removesuffix(".git"))
    return bool(match) and match.group("repo") == CANONICAL_REMOTE


def elastic_remote(root: Path) -> tuple[str, str]:
    """The canonical repo, under either remote name, so a clone named `origin` still passes."""
    found = subprocess.run(["git", "-C", str(root), "remote", "-v"],
                           capture_output=True, text=True)
    if found.returncode:
        return "", "not a git checkout"
    for line in found.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if is_canonical_remote(parts[1]):
            return parts[0], ""
    return "", f"no remote points at {CANONICAL_REMOTE}"


def build_is_fresh(root: Path) -> tuple[bool, str]:
    """A server serving an older build than HEAD runs code nobody reviewed."""
    build_id = root / ".next" / "BUILD_ID"
    head = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%ct"],
                          capture_output=True, text=True)
    if not build_id.is_file():
        return False, "no build; run npm run launchd:restart-web"
    if head.returncode or not head.stdout.strip():
        return True, ""
    if build_id.stat().st_mtime < int(head.stdout.strip()):
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
    log = DEFAULT_DIR / "data" / "logs" / "web.log"
    tail = ""
    if log.is_file():
        lines = log.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:]
        tail = "\n".join(lines)
    detail = f"{label} is not loaded; run npm run launchd:install"
    return False, f"{detail}\n{tail}" if tail else detail


def dev_stack_current(root: Path, stack: str | None) -> tuple[bool, str]:
    """The installed dev_stack.sh is a user-owned copy of examples/kibana-dev-tools/dev_stack.sh.

    Nightshift exports DEV_STACK_EIS=1 on every deploy because a stack without EIS has no chat
    model and e2e ends `blocked`; an older copy ignores the variable and never wires EIS in.
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


PORTS_TO_CHECK = (5601, 9200)


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def ports_status() -> tuple[bool, str]:
    """A deploy that lands on an already-bound port clashes with whatever is listening there
    (a prior stack, Scout, a local ES). This is a note, not a hard gate: a worktree that
    legitimately already has its own stack running is the normal case, not a problem."""
    busy = [str(port) for port in PORTS_TO_CHECK if port_in_use(port)]
    if not busy:
        return True, f"{', '.join(str(p) for p in PORTS_TO_CHECK)} are free"
    return False, f"port(s) {', '.join(busy)} already have a listener"


def duplicate_config_keys(path: Path) -> list[str]:
    """A hand-edited config.local.json can carry two keys with the same name; JSON parsing
    silently keeps only the last one, so the duplicate never surfaces unless something scans
    the raw pairs before they collapse."""
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


def helper_up_to_date(root: Path, remote: str) -> tuple[bool, str]:
    """Best-effort only: a `git fetch` failure (offline, auth) must never block or hang the
    preflight, so any error here is reported as unknown, not as a failing check."""
    if not remote:
        return True, "no elastic remote to compare against"
    try:
        fetch = subprocess.run(["git", "-C", str(root), "fetch", remote, "--quiet"],
                               capture_output=True, text=True, timeout=20)
        if fetch.returncode:
            return True, "could not reach the remote to check; skipping"
        head = subprocess.run(["git", "-C", str(root), "symbolic-ref", "--short", "-q", "HEAD"],
                              capture_output=True, text=True, timeout=5)
        branch = head.stdout.strip() if head.returncode == 0 else ""
        if not branch:
            return True, "detached HEAD; skipping"
        behind = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count", f"HEAD..{remote}/{branch}"],
            capture_output=True, text=True, timeout=5)
        if behind.returncode or not behind.stdout.strip().isdigit():
            return True, "could not compute how far behind HEAD is; skipping"
        count = int(behind.stdout.strip())
        if count == 0:
            return True, f"up to date with {remote}/{branch}"
        return False, f"{count} commit(s) behind {remote}/{branch}"
    except (subprocess.TimeoutExpired, OSError) as error:
        return True, f"check failed ({error}); skipping"


def tail_fatal(worktree_path: str) -> str:
    """The dev-stack log often buries the real failure under an earlier, harmless-looking
    line (e.g. a missing build artifact); the last FATAL line is the one worth surfacing."""
    log = Path(worktree_path).expanduser() / ".dev-stack" / "kibana.log"
    if not log.is_file():
        return ""
    try:
        fatal = [line for line in log.read_text(errors="replace").splitlines() if "FATAL" in line]
    except OSError:
        return ""
    return fatal[-1] if fatal else ""


def agent_check(cli: str) -> tuple[bool, str]:
    """Ask nightshift whether the harness works; a 502 carries its own install message."""
    try:
        payload = request("GET", f"/api/agents?cli={cli}", timeout=30)
    except ApiError as error:
        return False, str(error)
    except Unreachable as error:
        return False, f"server unreachable: {error}"
    models = payload.get("models")
    if not models:
        return False, f"no {cli} models available; check its installation and sign-in"
    return True, ""


def check(name: str, ok: bool, detail: str, fix: str = "") -> dict:
    return {"check": name, "ok": ok, "detail": detail, "fix": fix if not ok else ""}


def doctor(_args: argparse.Namespace) -> int:
    """Preflight for `crew e2e`, with checks ordered by what actually blocks a run.

    Nothing here is a warning: `crew e2e` starts real e2e runs, so a check that cannot pass
    must stop the skill. `launchd` and `build_fresh` are the exception, and deliberately so:
    a server started with `npm run dev` answers and works, so gating on a LaunchAgent would
    reject a perfectly usable machine. They are reported as notes instead.
    """
    root, source = resolve_root()
    checks: list[dict] = []
    notes: list[dict] = []
    checks.append(check("location", root.is_dir(), f"{root} ({source})",
                        "set NIGHTSHIFT_PR_HELPER_DIR to a nightshift-pr-helper checkout"))
    if not root.is_dir():
        print(json.dumps({"root": str(root), "url": base_url(), "ok": False,
                          "checks": checks, "notes": notes}, indent=2))
        return 1

    remote, why = elastic_remote(root)
    checks.append(check("repo", bool(remote), why or f"{remote} -> {CANONICAL_REMOTE}",
                        f"add the canonical remote: git -C {root} remote add elastic "
                        f"https://github.com/{CANONICAL_REMOTE}"))
    fresh, why = helper_up_to_date(root, remote)
    notes.append(check("helper_up_to_date", fresh, why,
                       f"cd {root} && git pull {remote}"))
    dupes = duplicate_config_keys(root / "config.local.json")
    notes.append(check("config_duplicate_keys", not dupes,
                       f"duplicate key(s) in config.local.json: {', '.join(sorted(set(dupes)))}"
                       if dupes else "no duplicate keys in config.local.json",
                       "remove the duplicate key(s); the later one silently wins over the earlier one"))
    free, why = ports_status()
    notes.append(check("ports_free", free, why,
                       f"a process already listens on that port; stop it, or pick a worktree "
                       "that is not already using it"))
    modules = root / "node_modules"
    checks.append(check("node_modules", modules.is_dir(), str(modules), f"cd {root} && npm install"))

    running, why = launchd_state()
    notes.append(check("launchd", running, why or "dev.prhelper.web is loaded",
                       f"cd {root} && npm run launchd:install"))
    # `.next/BUILD_ID` belongs to the launchd production server; a `npm run dev` server never
    # reads it, so its age says nothing and a restart would target a service that is not loaded.
    if running:
        fresh, why = build_is_fresh(root)
        notes.append(check("build_fresh", fresh, why or "build is newer than HEAD",
                           f"cd {root} && npm run launchd:restart-web"))

    # The queue endpoint is the only read-only proof that the port answers nightshift and
    # can report its machines. `/api/state` is not used: it advances the queue, which can
    # start a run this command was never asked to start.
    try:
        queue = request("GET", "/api/e2e/queue", timeout=15)
    except Unreachable as error:
        checks.append(check("server", False, f"{base_url()} unreachable: {error}",
                            f"cd {root} && npm run dev   # or npm run launchd:install"))
        print(json.dumps({"root": str(root), "url": base_url(), "ok": False,
                          "checks": checks, "notes": notes}, indent=2))
        return 1
    except ApiError as error:
        checks.append(check("server", False, f"{base_url()} answered: {error}",
                            f"cd {root} && npm run launchd:restart-web"))
        print(json.dumps({"root": str(root), "url": base_url(), "ok": False,
                          "checks": checks, "notes": notes}, indent=2))
        return 1
    shaped = isinstance(queue.get("queued"), list) and isinstance(queue.get("machines"), list)
    checks.append(check("server", shaped, f"{base_url()} /api/e2e/queue",
                        f"cd {root} && npm run launchd:restart-web"))
    machines = queue.get("machines") if shaped else []
    enabled = [m for m in machines if isinstance(m, dict) and m.get("enabled")]
    checks.append(check("machine_enabled", bool(enabled),
                        ", ".join(str(m.get("label") or m.get("id")) for m in enabled) or "no machine enabled",
                        "enable a review machine at /e2e, or set e2e.machines in config.local.json"))

    cli = _configured_cli(root)
    if cli is None:
        checks.append(check("config", False, "could not load config through nightshift's loader",
                            f"cd {root} && npm install"))
        print(json.dumps({"root": str(root), "url": base_url(), "ok": False,
                          "checks": checks, "notes": notes}, indent=2))
        return 1
    missing = [(name, path, flag) for name, path, flag in (
        ("kibana.repo", cli.get("kibana"), cli.get("kibanaExists")),
        ("nightshiftRepo", cli.get("nightshift"), cli.get("nightshiftExists")),
        ("kibana.devStackScript", cli.get("stack"), cli.get("stackExists")),
    ) if not path or not flag]
    checks.append(check("config_paths", not missing,
                        ", ".join(f"{name}={path}" for name, path, _ in missing)
                        or "all configured paths exist",
                        f"fix in {root}/config.local.json: "
                        + ", ".join(f"{name} ({path})" for name, path, _ in missing)))
    current, why = dev_stack_current(root, cli.get("stack"))
    notes.append(check("dev_stack_eis", current, why or "dev_stack.sh honors DEV_STACK_EIS",
                       f"review `diff {cli.get('stack')} {root}/examples/kibana-dev-tools/dev_stack.sh`, "
                       "back up the installed script, then copy the example over it"))
    checks.append(check("e2e_enabled", bool(cli.get("e2e")), "e2e.enabled is true",
                        f"set e2e.enabled in {root}/config.json"))
    checks.append(check("config", True, f"agent.cli={cli.get('cli')}"))
    cli_name = str(cli.get("cli") or "")
    usable, why = agent_check(cli_name) if cli_name else (False, "agent.cli is not set")
    checks.append(check("agent_cli", usable, why or f"{cli_name} reports models",
                        f"install and sign in to {cli_name}, or override agent.cli in {root}/config.local.json"))
    ok = all(entry["ok"] for entry in checks)
    print(json.dumps({"root": str(root), "url": base_url(), "ok": ok,
                      "checks": checks, "notes": notes}, indent=2))
    return 0 if ok else 1


def _configured_cli(root: Path) -> dict | None:
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
    result = subprocess.run([node, "--import", "tsx/esm", "--eval", script],
                            capture_output=True, text=True, cwd=root)
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return None


def worktrees(_args: argparse.Namespace) -> int:
    payload = request("GET", "/api/deploy?scope=designated")
    items = payload.get("worktrees") or []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = {key: item.get(key)
                 for key in ("id", "label", "name", "branch", "kibanaPort", "kibanaRunning", "path")}
        dirty = item.get("dirty")
        entry["dirty"] = dirty if isinstance(dirty, list) else []
        entry["dirtyCount"] = len(entry["dirty"])
        # Port 5601 is the documented convention for the user's own dev checkout (this skill's
        # Known limits say so); a dedicated e2e worktree normally runs elsewhere. A heuristic,
        # not a fact from the API, so it is named as risk, not as a verdict.
        entry["mainRepoRisk"] = entry.get("kibanaPort") == 5601
        result.append(entry)
    print(json.dumps({"worktrees": result}, indent=2))
    return 0


def start(args: argparse.Namespace) -> int:
    check_key(args.key)
    body = {"action": "start", "worktree": args.worktree, "deploy": bool(args.deploy)}
    if args.instructions:
        body["instructions"] = args.instructions
    payload = request("POST", f"/api/e2e/{args.key}", body)
    print(json.dumps({"started": payload, "run": f"{base_url()}/pr/{args.key}/e2e"}, indent=2))
    return 0


def status(args: argparse.Namespace) -> int:
    check_key(args.key)
    payload = request("GET", f"/api/e2e/{args.key}")
    state = (payload.get("status") or {}).get("state")
    result = {
        "key": args.key,
        "state": state,
        "finished": state in {"done", "failed"},
        "outdated": payload.get("outdated"),
        "testedHead": (payload.get("meta") or {}).get("headSha"),
        "error": (payload.get("status") or {}).get("error"),
        "worktree": (payload.get("meta") or {}).get("worktreeLabel")
        or (payload.get("meta") or {}).get("worktree"),
        "run": f"{base_url()}/pr/{args.key}/e2e",
    }
    # Nightshift's own `error` field is often the first thing that went wrong (a missing build
    # artifact), not the real cause; the dev-stack log's last FATAL line usually is.
    if state == "failed" and args.worktree_path:
        fatal = tail_fatal(args.worktree_path)
        if fatal:
            result["fatal"] = fatal
    print(json.dumps(result, indent=2))
    return 0


# Nightshift's own rule (prompts/e2e-common-report.md): only these observations, on a check
# that was not skipped, count as end-to-end. `via` is a list there; accept a bare string too.
END_TO_END_VIA = {"ui", "api", "es", "log"}


def is_end_to_end(entry: dict) -> bool:
    via = entry.get("via")
    observed = {str(item).lower() for item in (via if isinstance(via, list) else [via])}
    return entry.get("status") != "skipped" and bool(observed & END_TO_END_VIA)


def report(args: argparse.Namespace) -> int:
    check_key(args.key)
    payload = request("GET", f"/api/e2e/{args.key}")
    report_payload = payload.get("report")
    if not report_payload:
        state = (payload.get("status") or {}).get("state") or "unknown"
        print(f"nightshift-e2e: no report yet (state: {state})", file=sys.stderr)
        return 1
    checks = [dict(c, end_to_end=is_end_to_end(c)) for c in report_payload.get("checks") or []
              if isinstance(c, dict)]
    print(json.dumps({
        "key": args.key,
        "verdict": report_payload.get("verdict"),
        "summary": report_payload.get("summary"),
        "prIntent": report_payload.get("prIntent"),
        "approach": report_payload.get("approach"),
        "uiChanges": report_payload.get("uiChanges"),
        "outdated": payload.get("outdated"),
        "testedHead": (payload.get("meta") or {}).get("headSha") or report_payload.get("headSha"),
        "setup": report_payload.get("setup") or [],
        "checks": checks,
        # A check observed only through a health probe, a unit command or a script is not
        # end-to-end evidence; name them so a green run cannot be read as more than it is.
        "not_end_to_end": [c.get("title") for c in checks
                           if not c["end_to_end"] and c.get("status") != "skipped"],
        "findings": report_payload.get("findings") or [],
        "environmentChanges": report_payload.get("environmentChanges") or [],
        "notCovered": report_payload.get("notCovered") or [],
    }, indent=2))
    return 0


def followup(args: argparse.Namespace) -> int:
    check_key(args.key)
    if not args.text.strip():
        print("nightshift-e2e: empty follow-up", file=sys.stderr)
        return 2
    request("POST", f"/api/e2e/{args.key}", {"action": "followup", "question": args.text.strip()})
    print(json.dumps({"followup": args.key, "question": args.text.strip()}))
    return 0


def stop(args: argparse.Namespace) -> int:
    check_key(args.key)
    request("POST", f"/api/e2e/{args.key}", {"action": "stop"})
    print(json.dumps({"stopped": args.key}))
    return 0


def stack_stop(args: argparse.Namespace) -> int:
    """Stop the Kibana/ES stack nightshift started in a worktree; it does not touch the run
    or the checkout (`restore` would revert it, so it is deliberately not offered)."""
    request("POST", "/api/deploy", {"action": "stop-stack", "worktree": args.worktree})
    print(json.dumps({"stack_stopped": args.worktree}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="read-only preflight: repo, build, server, machine, agent CLI")
    commands.add_parser("worktrees", help="list designated Kibana worktrees")

    start_parser = commands.add_parser("start", help="start an e2e run (never queued, never comments)")
    start_parser.add_argument("key")
    start_parser.add_argument("--worktree", required=True)
    start_parser.add_argument("--deploy", action="store_true", help="deploy the PR into that worktree first")
    start_parser.add_argument("--instructions", default="", help="extra focus for the tester")

    for name, handler, help_text in (
        ("status", status, "run state"),
        ("report", report, "the finished report"),
        ("stop", stop, "stop the run"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("key")
        if name == "status":
            sub.add_argument("--worktree-path", default="",
                             help="local path to the deployed worktree, to tail its log on failure")

    stack_parser = commands.add_parser("stack-stop", help="stop the Kibana/ES stack in a worktree")
    stack_parser.add_argument("--worktree", required=True)

    followup_parser = commands.add_parser("followup", help="ask the tester a follow-up question")
    followup_parser.add_argument("key")
    followup_parser.add_argument("text")

    args = parser.parse_args()
    handlers = {"doctor": doctor, "worktrees": worktrees, "start": start,
                "status": status, "report": report, "followup": followup, "stop": stop,
                "stack-stop": stack_stop}
    try:
        return handlers[args.command](args)
    except Unreachable as error:
        print(f"nightshift-e2e: {base_url()} unreachable: {error}", file=sys.stderr)
        return UNREACHABLE
    except ApiError as error:
        print(f"nightshift-e2e: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"nightshift-e2e: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
