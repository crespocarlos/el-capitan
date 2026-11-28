"""`crew-verify.py`: run the repository's CI the way CI runs it, and record one exit code per gate.

The mirror runs each base-branch workflow `run:` step under the pinned Node, `CI=true` and the workflow
env (`task_verify_sources`).
Prints `<name> exit=<N>` lines and a JSON result (`schema_version: 1`); `--background`/`--wait <json>`
detach. Exit codes: 0 pass, 1 failed gate, 2 or 3 NOT VERIFIED, 4 still running.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from crew.lib.cli import EXIT_INVALID
from crew.lib.clock import utc_iso
from crew.lib.files import atomic_write
from crew.lib.git import GitError, base_ref, toplevel
from crew.task.task_verify_env import (
    EXIT_NOT_VERIFIED,
    cache_get,
    cache_key,
    cache_put,
    gate_line,
    is_partial,
    kinds,
    log_of,
    node_env,
    not_ci,
    partial_exit,
    partial_line,
    run_argv,
    tree_key,
    write_failed,
    write_result,
)
from crew.task.task_verify_sources import resolve

RUNNER_DEFAULTS = {"CI": "true", "GITHUB_ACTIONS": "true"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="crew-verify.py",
        description=__doc__.split("\n\n")[0],
        epilog="crew-verify.py report-check REPORT.md [--gates JSON] checks a builder report against a run (its own --help).",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="the tree to verify (default: cwd)")
    parser.add_argument("--task-dir", type=lambda value: Path(value) if value else None, default=None, help="writes <task-dir>/gates.json")
    parser.add_argument("--out", type=Path, default=None, help="the JSON result file")
    parser.add_argument("--base", default=None, help="the ref whose declaration is read (default: origin's default)")
    parser.add_argument("--only", default="", help="comma-separated gate names to run")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds per gate")
    parser.add_argument("--no-cache", action="store_true", help="re-run even a cached pass")
    parser.add_argument("--strict", action="store_true", help="exit 2 (not 3) for a partial run or only prose checks")
    parser.add_argument("--list", action="store_true", help="print the gates and their source; run nothing")
    parser.add_argument("--background", action="store_true", help="run detached; poll with --wait")
    parser.add_argument("--wait", type=Path, default=None, metavar="JSON", help="wait for a background run")
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="with --wait: give up after this long, exit 4 (default: no limit while the run's pid is alive)",
    )
    return parser.parse_args(argv)


def out_path(args: argparse.Namespace) -> Path | None:
    directory = args.task_dir or (Path(os.environ["CREW_TASK_DIR"]) if os.environ.get("CREW_TASK_DIR") else None)
    return args.out or (directory / "gates.json" if directory else None)


def run_command(gate: dict, root: Path, env: dict, timeout: int, log: Path) -> tuple[int, float]:
    shell = ["bash", "-e", "-o", "pipefail", "-c"] if shutil.which("bash") else ["sh", "-e", "-c"]
    return run_argv([*shell, gate["command"]], root / gate["cwd"], env, timeout, log)


def run_gate(gate: dict, root: Path, tree: str, node: dict, path: str, args: argparse.Namespace, log_dir: Path) -> dict:
    """One gate's record; a cached pass is reused unless `--no-cache`."""
    mirrored = {**RUNNER_DEFAULTS, **gate["env"]}
    key = cache_key(tree, gate["command"], mirrored, node["used"])
    record = {"name": gate["name"], "command": gate["command"], "env": mirrored, "node_version": node["used"], "exit": 0, "duration_s": 0.0, "cached": False}
    hit = None if args.no_cache else cache_get(root, key)
    if hit and hit.get("exit") == 0:
        return {**record, "duration_s": hit.get("duration_s", 0.0), "cached": True}
    code, seconds = run_command(gate, root, {**os.environ, "PATH": path, **mirrored}, args.timeout, log_dir / f"{gate['name']}.log")
    if code == 0:
        cache_put(root, key, {"exit": 0, "duration_s": seconds})
    return {**record, "exit": code, "duration_s": seconds}


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
    return {
        "schema_version": 1,
        "state": state,
        "verified": bool(declared["gates"]) and not is_partial(declared["skipped"]),
        "source": declared["source"],
        "base": base,
        "notes": declared["notes"],
        "skipped": declared["skipped"],
        "node": node,
        "tree": tree,
        "ci_unreadable": declared["ci_unreadable"],
        "prose_checks": declared["prose_checks"],
        "partial": is_partial(declared["skipped"]),
        "pid": os.getpid(),
        "started": utc_iso(),
        "gates": [],
    }


def unverified(args: argparse.Namespace, root: Path, base: str, declared: dict, out: Path | None) -> int:
    """No runnable gate: surface the prose checks (never run), say so loudly, never report a pass."""
    node, _ = node_env(declared["pin"])
    for item in declared["prose_checks"]:
        print(f"repo-declared check, run this: {item['command']}  [from {item['from']}]")
    print("verify: NOT VERIFIED: no gates declared (CI workflow, AGENTS.md gates block, .agent/gates.json). This is not a pass.")
    code = EXIT_INVALID if args.strict or not declared["prose_checks"] else EXIT_NOT_VERIFIED
    write_result(out, {**new_payload(base, declared, node, tree_key(root), "done"), "verdict_exit": code})
    return code


def run_all(args: argparse.Namespace, root: Path, base: str, declared: dict, out: Path | None) -> int:
    node, path = node_env(declared["pin"])
    print("no Node pin found, using PATH" if node["source"] == "none" else f"node: required {node['required']} ({node['source']}), using {node['used']}")
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
        return wait(args.wait, args.wait_timeout)
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
    """`--list` prints the gates; otherwise the mirror runs them."""
    found = declaration(args)
    if found is None:
        write_failed(out, "the repository or its base ref could not be resolved")
        return 2
    if args.list:
        print("\n".join(f"{g['name']}: {g['command'].splitlines()[0]}" for g in found[2]["gates"]))
        return 0
    return run_all(args, *found, out) if found[2]["gates"] else unverified(args, *found, out)


NO_PID_GRACE = 30  # seconds a payload may go without a recorded pid before --wait calls the run failed
EXIT_STILL_RUNNING = 4


def now() -> str:
    return utc_iso()


def print_lines(result: dict) -> None:
    for gate in result["gates"]:
        print(gate_line(gate))


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
        child = subprocess.Popen(
            [sys.executable, "-m", "crew.task.crew_verify", *rest, "--out", str(out)], stdout=handle, stderr=subprocess.STDOUT, start_new_session=True
        )
    if read(out).get("state") == "starting":  # the child's own payloads carry its pid too
        atomic_write(out, json.dumps({**starting, "pid": child.pid}) + "\n")
    print(f"started pid={child.pid} out={out} (wait: crew-verify.py --wait {out})")
    return 0


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


def answer(result: dict, path: Path) -> int | None:
    """The exit code a finished (`done` or `failed`) result gives, or None while it is not finished."""
    if result.get("state") == "failed":
        print(f"verify: NOT VERIFIED: the run failed: {result.get('reason')} (log: {log_of(path)})", file=sys.stderr)
        return 2
    if result.get("state") != "done":
        return None
    if result.get("partial") and result["gates"]:
        print(partial_line(result["skipped"]))
    print_lines(result)
    if result.get("verified", True):
        return 0 if all(g["exit"] == 0 for g in result["gates"]) else 1
    if not result["gates"]:
        print("verify: NOT VERIFIED: no gates declared (CI workflow, AGENTS.md gates block, .agent/gates.json). This is not a pass.")
    return int(result.get("verdict_exit", 3))


def wait(path: Path, wait_timeout: int | None) -> int:
    """Block until the run at `path` finishes, its child dies, or `wait_timeout` seconds pass (exit 4)."""
    started = time.monotonic()
    while wait_timeout is None or time.monotonic() - started < wait_timeout:
        result = read(path)
        code = answer(result, path)
        if code is not None:
            return code
        pid = result.get("pid")
        gone = not alive(pid) if pid is not None else time.monotonic() - started > NO_PID_GRACE
        if gone:
            code = answer(read(path), path)
            if code is not None:
                return code
            what = f"pid {pid} exited" if pid is not None else "no running verify is recorded"
            print(f"verify: NOT VERIFIED: the run failed: {what} without a result (log: {log_of(path)})", file=sys.stderr)
            return 2
        time.sleep(float(os.environ.get("CREW_VERIFY_POLL_SECONDS") or 1))  # how often --wait reads the result
    print(f"verify: {path} still running after {wait_timeout}s; do not hand off (log: {log_of(path)})", file=sys.stderr)
    return EXIT_STILL_RUNNING


def note_lines(declared: dict) -> list[str]:
    """The lines printed before any gate runs: the verdict of a partial mirror, the workflow files, what was skipped."""
    gates = declared["gates"]
    files = sorted({g["workflow"] for g in gates if g.get("workflow")})
    setup, other, uses = kinds(declared["skipped"])
    lines = [partial_line(declared["skipped"])] if other and gates else []
    lines += [f"workflows: {', '.join(files)}"] if files else []
    if setup or other:
        lines.append(f"skipped: {len(setup) + len(other)} steps ({'; '.join(setup + other)})")
    if uses:
        lines.append(f"not mirrored: {len(uses)} uses: steps")
    if not_ci(declared["skipped"]):
        lines.append(f"not CI: {'; '.join(not_ci(declared['skipped']))}")
    return lines
