"""`crew-progress.py verify`: run the repository's gates the way its CI runs them, and record the result.

Hosted by `crew-progress.py` (which already records what a stage did into the task directory) as a
subcommand, so no new top-level command exists. The commands come from the BASE branch's declaration
(`task_verify_sources.py`), run under the Node `.nvmrc` names, with the runner defaults `CI=true` and
`GITHUB_ACTIONS=true` plus the workflow's own env, in the workflow's step order. It prints one
`<name> exit=<N>` line per gate and writes a JSON file (`schema_version: 1`) with the command, env,
Node version, exit code and duration of each. A passing result is cached by (tree hash, command, env,
Node version). `--background` runs detached; `--wait <json>` blocks until that run is done (exit 4
when `--wait-timeout` runs out first). Exit codes: 0 pass, 1 failed gate, 2 or 3 NOT VERIFIED, 4 still running.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lib.files import atomic_write
from lib.git import GitError, base_ref, toplevel
from task_verify_env import cache_get, cache_key, cache_put, node_env, tree_key
from task_verify_notes import is_partial, note_lines, partial_exit
from task_verify_resolve import resolve
from task_verify_wait import background, gate_line, wait, write_failed

RUNNER_DEFAULTS = {"CI": "true", "GITHUB_ACTIONS": "true"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="crew-progress.py verify", description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="the tree to verify (default: cwd)")
    parser.add_argument("--task-dir", type=lambda value: Path(value) if value else None, default=None, help="writes <task-dir>/gates.json")
    parser.add_argument("--out", type=Path, default=None, help="the JSON result file")
    parser.add_argument("--base", default=None, help="the ref whose declaration is read (default: origin's default)")
    parser.add_argument("--only", default="", help="comma-separated gate names to run")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds per gate")
    parser.add_argument("--no-cache", action="store_true", help="re-run even a cached pass")
    parser.add_argument("--strict", action="store_true", help="exit 2 (not 3) when only prose checks were found")
    parser.add_argument("--list", action="store_true", help="print the gates and their source; run nothing")
    parser.add_argument("--background", action="store_true", help="run detached; poll with --wait")
    parser.add_argument("--wait", type=Path, default=None, metavar="JSON", help="wait for a background run")
    parser.add_argument("--since", default=None, help="with --wait: ignore a result older than this ISO time (printed by --background)")
    parser.add_argument("--wait-timeout", type=int, default=None, metavar="SECONDS",
                        help="with --wait: give up after this long, exit 4 (default: no limit while the run's pid is alive)")
    return parser.parse_args(argv)


def out_path(args: argparse.Namespace) -> Path | None:
    directory = args.task_dir or (Path(os.environ["CREW_TASK_DIR"]) if os.environ.get("CREW_TASK_DIR") else None)
    return args.out or (directory / "gates.json" if directory else None)


def run_command(gate: dict, root: Path, env: dict, timeout: int, log: Path) -> tuple[int, float]:
    shell = ["bash", "-e", "-o", "pipefail", "-c"] if shutil.which("bash") else ["sh", "-e", "-c"]
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        try:
            done = subprocess.run([*shell, gate["command"]], cwd=root / gate["cwd"], env=env,
                                  stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
            code = done.returncode
        except subprocess.TimeoutExpired:
            code = 124
        except OSError as error:
            handle.write(f"cannot run: {error}\n")
            code = 127
    return code, round(time.monotonic() - started, 2)


def run_gate(gate: dict, root: Path, tree: str, node: dict, path: str, args: argparse.Namespace,
             log_dir: Path) -> dict:
    """One gate's record; a cached pass is reused unless `--no-cache`."""
    mirrored = {**RUNNER_DEFAULTS, **gate["env"]}
    key = cache_key(tree, gate["command"], mirrored, node["used"])
    record = {"name": gate["name"], "command": gate["command"], "env": mirrored, "node_version": node["used"],
              "exit": 0, "duration_s": 0.0, "cached": False}
    hit = None if args.no_cache else cache_get(root, key)
    if hit and hit.get("exit") == 0:
        return {**record, "duration_s": hit.get("duration_s", 0.0), "cached": True}
    code, seconds = run_command(gate, root, {**os.environ, "PATH": path, **mirrored}, args.timeout,
                                log_dir / f"{gate['name']}.log")
    if code == 0:
        cache_put(root, key, {"exit": 0, "duration_s": seconds})
    return {**record, "exit": code, "duration_s": seconds}


def write_result(out: Path | None, payload: dict) -> None:
    if out is not None:
        atomic_write(out, json.dumps(payload, indent=2) + "\n")


def declaration(args: argparse.Namespace) -> tuple[Path, str, dict] | None:
    """`(root, base, declared)` with the notes and source printed, or None when nothing is declared."""
    try:
        root = toplevel(args.repo)
        base = args.base or base_ref(root)
    except GitError as error:
        print(f"verify: {error}", file=sys.stderr)
        return None
    declared = resolve(root, None if base == "HEAD~1" else base)
    wanted = {n for n in args.only.split(",") if n}
    declared["gates"] = [g for g in declared["gates"] if not wanted or g["name"] in wanted]
    print("\n".join([*declared["notes"], f"source: {declared['source']}", *note_lines(declared)]))
    return root, base, declared


def new_payload(base: str, declared: dict, node: dict, tree: str, state: str) -> dict:
    """The result JSON before any gate ran; every key after `schema_version` is additive."""
    return {"schema_version": 1, "state": state, "verified": bool(declared["gates"]) and not is_partial(declared["skipped"]), "source": declared["source"],
            "base": base, "notes": declared["notes"], "skipped": declared["skipped"], "node": node, "tree": tree,
            "ci_unreadable": declared["ci_unreadable"], "prose_checks": declared["prose_checks"],
            "partial": is_partial(declared["skipped"]), "pid": os.getpid(),
            "started": datetime.now(timezone.utc).isoformat(), "gates": []}


def unverified(args: argparse.Namespace, root: Path, base: str, declared: dict, out: Path | None) -> int:
    """No runnable gate: surface the prose checks (never run), say so loudly, never report a pass."""
    node, _ = node_env(declared["pin"])
    for item in declared["prose_checks"]:
        print(f"repo-declared check, run this: {item['command']}  [from {item['from']}]")
    print("verify: NOT VERIFIED: no gates declared (CI workflow, AGENTS.md gates block, .agent/gates.json). This is not a pass.")
    code = 2 if args.strict or not declared["prose_checks"] else 3
    write_result(out, {**new_payload(base, declared, node, tree_key(root), "done"), "verdict_exit": code})
    return code


def run_all(args: argparse.Namespace, root: Path, base: str, declared: dict, out: Path | None) -> int:
    node, path = node_env(declared["pin"])
    print("no Node pin found, using PATH" if node["source"] == "none"
          else f"node: required {node['required']} ({node['source']}), using {node['used']}")
    tree = tree_key(root)
    payload = new_payload(base, declared, node, tree, "running")
    log_dir = (out.parent if out else root) / "verify-logs"
    for gate in declared["gates"]:
        payload["gates"].append(run_gate(gate, root, tree, node, path, args, log_dir))
        write_result(out, payload)
        print(gate_line(payload["gates"][-1]), flush=True)
    code = partial_exit(declared["skipped"], all(g["exit"] == 0 for g in payload["gates"]), args.strict)
    payload.update({"state": "done", "verdict_exit": code})
    write_result(out, payload)
    return code


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.wait:
        return wait(args.wait, args.wait_timeout, args.since)
    out = out_path(args)
    if args.background and args.list:
        print("verify: --background cannot be used with --list (a list run never writes a result to wait on)", file=sys.stderr)
        return 2
    if args.background:
        return background(argv, out)
    try:
        return execute(args, out)
    except Exception as error:  # a run that dies must leave `failed`, never a file --wait would wait on
        write_failed(out, f"{type(error).__name__}: {error}")
        raise


def execute(args: argparse.Namespace, out: Path | None) -> int:
    found = declaration(args)
    if found is None:
        write_failed(out, "the repository or its base ref could not be resolved")
        return 2
    if args.list:
        print("\n".join(f"{g['name']}: {g['command'].splitlines()[0]}" for g in found[2]["gates"]))
        return 0
    return run_all(args, *found, out) if found[2]["gates"] else unverified(args, *found, out)
