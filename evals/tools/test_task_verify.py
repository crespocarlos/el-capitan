#!/usr/bin/env python3
"""`crew-verify.py`: the repository's gates, run the way its CI runs them.

The fixture's test clears `CI` but not `GITHUB_ACTIONS`, which the workflow sets, so a mirror that
did not copy the runner env would pass it. Declarations come from the base branch, so a PR cannot
weaken the gates it is judged by. The removed `crew-progress.py verify` form exits 2.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / ".agent" / "tools" / "task"
CLI = TASK_TOOLS / "crew-verify.py"
sys.path.insert(0, str(TASK_TOOLS))
sys.path.insert(0, str(TASK_TOOLS.parent))
FAILED: list[str] = []

WORKFLOW = """name: CI
on:
  pull_request:
  push:
    branches: [main]
env:
  GITHUB_ACTIONS: "true"
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      LEVEL: {level}
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - name: Unit tests
        run: sh check.sh
      - name: Lint
        run: |
          echo lint
          test "$LEVEL" = "{level}"
"""
# The judge-CLI mistake: it clears `CI` and assumes that makes the environment clean.
CHECK = 'unset CI\ntest -z "$GITHUB_ACTIONS"\n'


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("pass: " if condition else "FAIL: ") + name + ("" if condition else f": {detail}"))
    if not condition:
        FAILED.append(name)


def git(root: Path, *arguments: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
    done = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, env=env)
    if done.returncode:
        raise RuntimeError(done.stderr)
    return done.stdout.strip()


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def fixture(tmp: Path, level: str = "1", workflow: bool = True) -> Path:
    root = tmp / "repo"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    write(root, "check.sh", CHECK)
    write(root, ".nvmrc", "22\n")
    if workflow:
        write(root, ".github/workflows/ci.yml", WORKFLOW.format(level=level))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def verify(root: Path, home: Path, *extra: str) -> tuple[int, str, dict]:
    out = root.parent / "gates.json"
    out.unlink(missing_ok=True)
    env = {**os.environ, "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null"}
    env.pop("CREW_TASK_DIR", None)
    done = subprocess.run([sys.executable, str(CLI), "--repo", str(root), "--base", "main",
                           "--out", str(out), *extra], capture_output=True, text=True, env=env)
    data = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return done.returncode, done.stdout + done.stderr, data


def fake_node(home: Path, version: str) -> None:
    binary = home / ".nvm" / "versions" / "node" / f"v{version}" / "bin" / "node"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(f"#!/bin/sh\necho v{version}\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)


def mirrors_the_runner(tmp: Path) -> None:
    root, home = fixture(tmp / "mirror"), tmp / "home1"
    home.mkdir(parents=True)
    fake_node(home, "22.1.0")
    code, out, data = verify(root, home)
    gates = {g["name"]: g for g in data.get("gates", [])}
    check("the CI workflow is the source", "source: ci-workflow .github/workflows@main" in out, out)
    check("the setup step is skipped, the others kept in step order", list(gates) == ["unit-tests", "lint"], list(gates))
    check("a test clearing only CI is caught (GITHUB_ACTIONS still set)", gates.get("unit-tests", {}).get("exit") == 1 and code == 1, out)
    check("it prints `name exit=N` lines", "unit-tests exit=1" in out and "lint exit=0" in out, out)
    check("the JSON is schema_version 1 with command, env, node, exit, duration",
          data.get("schema_version") == 1 and all(
              {"command", "env", "node_version", "exit", "duration_s"} <= set(g) for g in gates.values()), data)
    check("the mirrored env holds the runner defaults and the workflow env",
          gates["unit-tests"]["env"].get("GITHUB_ACTIONS") == "true" and gates["unit-tests"]["env"].get("CI") == "true"
          and gates["lint"]["env"].get("LEVEL") == "1", gates)
    check(".nvmrc selects the Node", data["node"]["used"] == "v22.1.0" and "using v22.1.0" in out, data.get("node"))
    plain = subprocess.run(["sh", "check.sh"], cwd=root, capture_output=True, env={"PATH": os.environ["PATH"]})
    check("the same test passes in a bare local shell, which is why the mirror matters", plain.returncode == 0)


def caching(tmp: Path) -> None:
    root, home = fixture(tmp / "cache"), tmp / "home2"
    home.mkdir(parents=True)
    fake_node(home, "22.1.0")
    verify(root, home)
    _, out, data = verify(root, home)
    cached = {g["name"]: g["cached"] for g in data["gates"]}
    check("a passing gate is cached on an unchanged tree", cached["lint"] is True, out)
    check("a failing gate is re-run, never replayed", cached["unit-tests"] is False, out)
    write(root, "new.txt", "x")
    _, _, data = verify(root, home)
    check("a changed tree misses the cache", data["gates"][1]["cached"] is False, data["gates"])
    (root / "new.txt").unlink()
    verify(root, home)
    fake_node(home, "22.9.0")
    _, _, data = verify(root, home)
    check("a changed Node version misses the cache", data["node"]["used"] == "v22.9.0" and data["gates"][1]["cached"] is False, data)
    write(root, ".github/workflows/ci.yml", WORKFLOW.format(level="2"))
    git(root, "commit", "-q", "-am", "change env")
    _, _, data = verify(root, home)
    check("a changed env misses the cache", data["gates"][1]["env"]["LEVEL"] == "2" and data["gates"][1]["cached"] is False, data["gates"])
    keys = __import__("task_verify_env")
    base = keys.cache_key("t", "cmd", {"A": "1"}, "v22.0.0")
    check("the key covers tree, command, env and node version",
          len({base, keys.cache_key("u", "cmd", {"A": "1"}, "v22.0.0"), keys.cache_key("t", "cmd2", {"A": "1"}, "v22.0.0"),
               keys.cache_key("t", "cmd", {"A": "2"}, "v22.0.0"), keys.cache_key("t", "cmd", {"A": "1"}, "v20.0.0")}) == 5)


def base_declaration_wins(tmp: Path) -> None:
    root, home = fixture(tmp / "head"), tmp / "home3"
    home.mkdir(parents=True)
    git(root, "checkout", "-q", "-b", "pr")
    write(root, ".github/workflows/ci.yml", "name: CI\non: push\njobs:\n  test:\n    steps:\n      - name: Weak\n        run: true\n")
    write(root, ".agent/gates.json", json.dumps({"schema_version": 1, "gates": [{"name": "weak", "command": "true"}]}))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "weaken the gates")
    _, out, data = verify(root, home)
    names = [g["name"] for g in data["gates"]]
    check("a PR-head edit to the declaration is ignored", names == ["unit-tests", "lint"], names)
    check("it says so", "declaration changed in PR head, using base" in out, out)
    check("a gates.json added in the PR head is ignored too", "override" not in data["source"], data["source"])


def fallback_order(tmp: Path) -> None:
    home = tmp / "home4"
    home.mkdir(parents=True)
    block = "# Repo\n\n```gates\nenv: LEVEL=7\nunit: echo unit\nlint: test \"$LEVEL\" = 7\n```\n"
    root = fixture(tmp / "agents", workflow=False)
    write(root, "AGENTS.md", block)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "agents gates")
    code, out, data = verify(root, home)
    check("no workflow: the AGENTS.md gates block answers", data.get("source") == "AGENTS.md gates block@main" and code == 0, out)
    check("the block's env and the source are printed", "source: AGENTS.md gates block@main" in out and data["gates"][1]["env"]["LEVEL"] == "7", out)
    write(root, ".agent/gates.json", json.dumps({"schema_version": 1, "gates": [{"name": "only", "command": "true"}]}))
    write(root, ".github/workflows/ci.yml", WORKFLOW.format(level="1"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "override and workflow")
    _, out, data = verify(root, home)
    names = [g["name"] for g in data["gates"]]
    check("CI is THE source: gates.json adds a gate, never replaces the CI gates (AGENTS.md ignored)",
          names == ["unit-tests", "lint", "only"] and "additions" in data["source"] and "ci-workflow" in data["source"], (names, out))
    only = fixture(tmp / "only", workflow=False)
    write(only, ".agent/gates.json", json.dumps({"schema_version": 1, "gates": [{"name": "solo", "command": "true"}]}))
    git(only, "add", "-A")
    git(only, "commit", "-q", "-m", "gates.json only")
    code, out, data = verify(only, home)
    check("gates.json as the only source is used as is", [g["name"] for g in data["gates"]] == ["solo"] and code == 0, out)
    bare = fixture(tmp / "bare", workflow=False)
    code, out, _ = verify(bare, home)
    check("nothing declared is an error that names the three sources", code == 2 and "no gates declared" in out, out)


def drift_warning(tmp: Path) -> None:
    root, home = fixture(tmp / "drift"), tmp / "home6"
    home.mkdir(parents=True)
    write(root, ".agent/gates.json", json.dumps({"schema_version": 1, "gates": [{"name": "lint", "command": "true"}]}))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "gates.json redefines lint")
    _, out, data = verify(root, home)
    lint = {g["name"]: g for g in data["gates"]}["lint"]
    check("a gates.json redefinition never changes the CI command", lint["command"].startswith("echo lint"), lint)
    check("the warning names the gate and both commands",
          "warning: gate lint" in out and "echo lint" in out and "'true'" in out, out)


def background_run(tmp: Path) -> None:
    root, home = fixture(tmp / "bg"), tmp / "home5"
    home.mkdir(parents=True)
    out = tmp / "bg" / "gates.json"
    env = {**os.environ, "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null"}
    started = subprocess.run([sys.executable, str(CLI), "--repo", str(root), "--base", "main", "--out", str(out),
                              "--background"], capture_output=True, text=True, env=env)
    check("--background prints started and returns at once", started.returncode == 0 and "started pid=" in started.stdout, started)
    waited = subprocess.run([sys.executable, str(CLI), "--wait", str(out), "--timeout", "60"],
                            capture_output=True, text=True, env=env)
    check("--wait prints the gate lines and the failing exit", "unit-tests exit=1" in waited.stdout and waited.returncode == 1, waited)


def cli(*arguments: str, home: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null"}
    return subprocess.run([sys.executable, str(CLI), *arguments], capture_output=True, text=True, env=env)


def stale_result_is_not_waited_on(tmp: Path) -> None:
    """A previous run's `done` file must not answer a new run that has not finished a gate yet."""
    root, home = fixture(tmp / "stale"), tmp / "home7"
    home.mkdir(parents=True)
    out = tmp / "stale" / "gates.json"
    out.write_text(json.dumps({"schema_version": 1, "state": "done", "verified": True, "started": "2020-01-01T00:00:00+00:00",
                               "gates": [{"name": "unit-tests", "exit": 0}]}), encoding="utf-8")
    cli("--repo", str(root), "--base", "main", "--out", str(out), "--background", home=home)
    waited = cli("--wait", str(out), "--timeout", "60", home=home)
    check("a stale done file is not the answer: the new failing gate is", "unit-tests exit=1" in waited.stdout and waited.returncode == 1, waited)
    starting = tmp / "stale" / "starting.json"
    starting.write_text(json.dumps({"schema_version": 1, "state": "starting", "pid": os.getpid(), "gates": []}), encoding="utf-8")
    slow = bounded("--wait", str(starting), "--wait-timeout", "1", home=home)
    check("a --wait-timeout on a live run exits 4 (still running) and names the log",
          slow is not None and slow.returncode == 4 and "starting.log" in slow.stderr and "still running" in slow.stderr, slow)


def bounded(*arguments: str, home: Path, seconds: int = 60) -> subprocess.CompletedProcess | None:
    """`cli` that gives up after `seconds`: None means the wait hung."""
    env = {**os.environ, "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null"}
    try:
        return subprocess.run([sys.executable, str(CLI), *arguments], capture_output=True, text=True, env=env, timeout=seconds)
    except subprocess.TimeoutExpired:
        return None


def wait_follows_the_child(tmp: Path) -> None:
    """--wait has no total limit while the recorded child lives; a dead child with no result is a failed run."""
    home = tmp / "home10"
    home.mkdir(parents=True)
    gone = subprocess.Popen(["true"])
    gone.wait()
    orphan = tmp / "orphan.json"
    orphan.write_text(json.dumps({"schema_version": 1, "state": "running", "pid": gone.pid, "started": "2030-01-01T00:00:00+00:00",
                                  "gates": [{"name": "unit", "exit": 0}]}), encoding="utf-8")
    done = bounded("--wait", str(orphan), home=home, seconds=30)
    check("a dead child with no done or failed payload is reported failed, naming the log",
          done is not None and done.returncode == 2 and "orphan.log" in done.stderr and "NOT VERIFIED" in done.stderr, done)
    root = fixture(tmp / "pid")
    out = tmp / "pid" / "gates.json"
    started = cli("--repo", str(root), "--base", "main", "--out", str(out), "--background", home=home)
    pid = started.stdout.split("pid=")[1].split()[0] if "pid=" in started.stdout else ""
    payload = json.loads(out.read_text(encoding="utf-8"))
    check("the starting payload records the child pid", str(payload.get("pid")) == pid and pid, (payload, started.stdout))
    waited = bounded("--wait", str(out), home=home)
    check("--wait with no --wait-timeout still returns the run's code", waited is not None and waited.returncode == 1, waited)
    refused = bounded("--repo", str(root), "--base", "main", "--out", str(tmp / "list.json"), "--background", "--list", home=home)
    check("--background with --list is refused with exit 2", refused is not None and refused.returncode == 2
          and "--list" in refused.stderr and not (tmp / "list.json").exists(), refused)


def early_exit_is_reported(tmp: Path) -> None:
    """A child that dies before its first gate writes `failed` with a reason, so --wait stops at once."""
    home = tmp / "home8"
    home.mkdir(parents=True)
    out = tmp / "gates.json"
    cli("--repo", str(tmp / "no-such-repo"), "--out", str(out), "--background", home=home)
    waited = cli("--wait", str(out), "--timeout", "10", home=home)
    state = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    check("an early exit writes state failed with a reason", state.get("state") == "failed" and state.get("reason"), state)
    check("--wait reports it and points at the log", waited.returncode == 2 and "gates.log" in waited.stderr + waited.stdout, waited)


def wait_matches_foreground_when_unverified(tmp: Path) -> None:
    home = tmp / "home9"
    home.mkdir(parents=True)
    bare = fixture(tmp / "bare", workflow=False)
    out = tmp / "bare" / "gates.json"
    foreground = cli("--repo", str(bare), "--base", "main", "--out", str(out), "--strict", home=home)
    cli("--repo", str(bare), "--base", "main", "--out", str(out), "--strict", "--background", home=home)
    waited = cli("--wait", str(out), "--timeout", "60", home=home)
    check("--wait returns the foreground code when nothing was verified", waited.returncode == foreground.returncode == 2, (waited, foreground))
    check("--wait prints the NOT VERIFIED line", "NOT VERIFIED" in waited.stdout + waited.stderr, waited)


def old_form_is_gone(tmp: Path) -> None:
    root = fixture(tmp / "old")
    done = subprocess.run([sys.executable, str(TASK_TOOLS / "crew-progress.py"), "verify", "--repo", str(root), "--base", "main",
                           "--list"], capture_output=True, text=True)
    check("`crew-progress.py verify` is an unknown argument (exit 2)", done.returncode == 2 and "unrecognized" in done.stderr, done)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for case in (mirrors_the_runner, caching, base_declaration_wins, fallback_order, drift_warning, background_run,
                     stale_result_is_not_waited_on, early_exit_is_reported, wait_matches_foreground_when_unverified,
                     wait_follows_the_child, old_form_is_gone):
            try:
                case(tmp / case.__name__)
            except (RuntimeError, KeyError, IndexError, OSError, ValueError) as error:
                check(case.__name__, False, f"{type(error).__name__}: {error}")
    for name in FAILED:
        print(f"failed: {name}", file=sys.stderr)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
