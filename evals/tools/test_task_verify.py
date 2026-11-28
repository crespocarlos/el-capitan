#!/usr/bin/env python3
"""`crew-verify.py`: the repository's gates, run the way its CI runs them, and the builder report checked against them.

The fixture's test clears `CI` but not `GITHUB_ACTIONS`, which the workflow sets, so a mirror that
did not copy the runner env would pass it. Declarations come from the base branch, so a PR cannot
weaken the gates it is judged by. In other repos verify picks the Node by the first pin, names CI it
cannot read, surfaces prose commands without running them, and never reports a pass with nothing
runnable. `report-check` refuses a REPORT.md that claims a gate other than as it exited. `--wait`
polls every 20 ms here (`CREW_VERIFY_POLL_SECONDS`); the cases run side by side, each in its own
directory, because each spends its time in git.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / "src" / "crew" / "task"
CLI = TASK_TOOLS / "crew_verify.py"
from cli_runner import run as run_cli  # noqa: E402

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
    assert condition, f"{name}: {detail}"


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


def cli(*arguments: str, home: Path) -> subprocess.CompletedProcess:
    """`crew-verify.py` in this process, its `--wait` polling every 20 ms instead of every second."""
    env = {"HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null", "CREW_VERIFY_POLL_SECONDS": "0.02", "CREW_TASK_DIR": None}
    return run_cli(CLI, *arguments, env=env)


def verify(root: Path, home: Path, *extra: str) -> tuple[int, str, dict]:
    out = root.parent / "gates.json"
    out.unlink(missing_ok=True)
    done = cli("--repo", str(root), "--base", "main", "--out", str(out), *extra, home=home)
    data = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return done.returncode, done.stdout + done.stderr, data


def fake_node(home: Path, version: str) -> None:
    binary = home / ".nvm" / "versions" / "node" / f"v{version}" / "bin" / "node"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(f"#!/bin/sh\necho v{version}\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)


def test_mirrors_the_runner(tmp: Path) -> None:
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


def test_caching(tmp: Path) -> None:
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
    from crew.task import task_verify_env as keys
    base = keys.cache_key("t", "cmd", {"A": "1"}, "v22.0.0")
    check("the key covers tree, command, env and node version",
          len({base, keys.cache_key("u", "cmd", {"A": "1"}, "v22.0.0"), keys.cache_key("t", "cmd2", {"A": "1"}, "v22.0.0"),
               keys.cache_key("t", "cmd", {"A": "2"}, "v22.0.0"), keys.cache_key("t", "cmd", {"A": "1"}, "v20.0.0")}) == 5)


def test_base_declaration_wins(tmp: Path) -> None:
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


def test_fallback_order(tmp: Path) -> None:
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


def test_drift_warning(tmp: Path) -> None:
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


def test_background_run(tmp: Path) -> None:
    root, home = fixture(tmp / "bg"), tmp / "home5"
    home.mkdir(parents=True)
    out = tmp / "bg" / "gates.json"
    started = cli("--repo", str(root), "--base", "main", "--out", str(out), "--background", home=home)
    check("--background prints started and returns at once", started.returncode == 0 and "started pid=" in started.stdout, started)
    waited = cli("--wait", str(out), "--timeout", "60", home=home)
    check("--wait prints the gate lines and the failing exit", "unit-tests exit=1" in waited.stdout and waited.returncode == 1, waited)


def test_stale_result_is_not_waited_on(tmp: Path) -> None:
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
    env = {**os.environ, "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null", "CREW_VERIFY_POLL_SECONDS": "0.02"}
    try:
        return subprocess.run([sys.executable, str(CLI), *arguments], capture_output=True, text=True, env=env, timeout=seconds)
    except subprocess.TimeoutExpired:
        return None


def test_wait_follows_the_child(tmp: Path) -> None:
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


def test_early_exit_is_reported(tmp: Path) -> None:
    """A child that dies before its first gate writes `failed` with a reason, so --wait stops at once."""
    home = tmp / "home8"
    home.mkdir(parents=True)
    out = tmp / "gates.json"
    cli("--repo", str(tmp / "no-such-repo"), "--out", str(out), "--background", home=home)
    waited = cli("--wait", str(out), "--timeout", "10", home=home)
    state = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    check("an early exit writes state failed with a reason", state.get("state") == "failed" and state.get("reason"), state)
    check("--wait reports it and points at the log", waited.returncode == 2 and "gates.log" in waited.stderr + waited.stdout, waited)


def test_wait_matches_foreground_when_unverified(tmp: Path) -> None:
    home = tmp / "home9"
    home.mkdir(parents=True)
    bare = fixture(tmp / "bare", workflow=False)
    out = tmp / "bare" / "gates.json"
    foreground = cli("--repo", str(bare), "--base", "main", "--out", str(out), "--strict", home=home)
    cli("--repo", str(bare), "--base", "main", "--out", str(out), "--strict", "--background", home=home)
    waited = cli("--wait", str(out), "--timeout", "60", home=home)
    check("--wait returns the foreground code when nothing was verified", waited.returncode == foreground.returncode == 2, (waited, foreground))
    check("--wait prints the NOT VERIFIED line", "NOT VERIFIED" in waited.stdout + waited.stderr, waited)


def pinned(tmp: Path, name: str, files: dict[str, str]) -> tuple[Path, Path]:
    """A repo with the CI workflow, no `.nvmrc`, and exactly `files` as its Node pin (if any)."""
    root, home = fixture(tmp / name), tmp / f"home-{name}"
    home.mkdir(parents=True)
    git(root, "rm", "-q", ".nvmrc")
    for path, text in files.items():
        write(root, path, text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "pin")
    return root, home


@pytest.mark.parametrize("name,files,installed,expected", [
    ("none", {}, "22.1.0", {"source": "none", "required": ""}),
    ("nodever", {".node-version": "20.1\n"}, "20.1.0", {"required": "20.1", "used": "v20.1.0", "source": ".node-version"}),
    ("tool", {".tool-versions": "python 3.11.2\nnodejs 18.2.0\n", "package.json": '{"engines": {"node": "22"}}'}, "18.2.0",
     {"source": ".tool-versions", "used": "v18.2.0"}),
    ("engines", {"package.json": '{"name": "x", "engines": {"node": "^20.3.0"}}'}, "20.3.0",
     {"required": "20.3.0", "used": "v20.3.0", "source": "package.json engines.node"}),
    ("nvmrc", {".nvmrc": "v22\n", ".node-version": "20\n"}, "22.1.0", {"source": ".nvmrc", "used": "v22.1.0"}),
])
def test_node_pin_order(name: str, files: dict[str, str], installed: str, expected: dict[str, str], tmp: Path) -> None:
    """The first pin found picks the Node: .nvmrc, .node-version, .tool-versions, engines.node; none forces nothing."""
    root, home = pinned(tmp, name, files)
    fake_node(home, installed)
    _, out, data = verify(root, home)
    check(f"Node pin {name}: {expected}", all(data["node"].get(k) == v for k, v in expected.items())
          and (name != "none" or ("no Node pin found, using PATH" in out and data["node"]["used"] != "v22.1.0")), data.get("node"))


def test_python_only(tmp: Path) -> None:
    """A Python repo is never forced onto Node: no pin file, even with a Node installed under HOME."""
    root, home = tmp / "py", tmp / "home-py"
    root.mkdir(parents=True)
    home.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    write(root, "pyproject.toml", "[project]\nname = 'x'\n")
    write(root, "AGENTS.md", "# Py\n\n```gates\nunit: python3 -c 'print(1)'\n```\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "py")
    fake_node(home, "22.1.0")
    code, out, data = verify(root, home)
    check("a Python-only repo runs its gate on the PATH's Node, records no pin, and keys the cache by it",
          code == 0 and data["gates"][0]["exit"] == 0 and "no Node pin found, using PATH" in out and data["node"]["source"] == "none"
          and data["node"]["used"] != "v22.1.0" and data["gates"][0]["node_version"] == data["node"]["used"], out)


KIBANA_ROOT = "# Kibana\n\nRun `node scripts/check.js --scope=local|staged|branch` before you push.\n\n## Tests\n\n```sh\nyarn test:jest --config x.js\n```\n"
KIBANA_NESTED = ("# Alerting\n\nRun `node scripts/check.js --scope=local` and then `yarn test:jest x-pack/plugins/alerting`.\n"
                 "Type check with `node scripts/type_check.js --project x-pack/plugins/alerting/tsconfig.json`.\n")


def committed(root: Path, files: dict[str, str], branch_edit: tuple[str, str] | None = None) -> Path:
    """A repo with `files` on main and, optionally, one edited file on a `feat` branch."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    for path, text in files.items():
        write(root, path, text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    if branch_edit:
        git(root, "checkout", "-q", "-b", "feat")
        write(root, *branch_edit)
        git(root, "commit", "-q", "-am", "touch")
    return root


def test_kibana_shape(tmp: Path) -> None:
    """Unreadable CI is named; the nearest AGENTS.md's prose commands are surfaced, never run, never a pass."""
    home = tmp / "home-kibana"
    home.mkdir(parents=True)
    root = committed(tmp / "kibana", {".nvmrc": "22.1.0\n", ".buildkite/pipelines/pull_request/base.yml": "steps:\n  - command: x.sh\n",
                                      "AGENTS.md": KIBANA_ROOT, "x-pack/plugins/alerting/AGENTS.md": KIBANA_NESTED,
                                      "x-pack/plugins/alerting/server/index.ts": "export const a = 1;\n",
                                      "x-pack/plugins/other/AGENTS.md": "# Other\n\nRun `node scripts/other_check.js`.\n",
                                      "x-pack/plugins/other/index.ts": "export const b = 1;\n"},
                     ("x-pack/plugins/alerting/server/index.ts", "export const a = 2;\n"))
    fake_node(home, "22.1.0")
    code, out, data = verify(root, home)
    check("Buildkite is named as unreadable CI, in the JSON too", "CI not readable here (buildkite)" in out and data.get("ci_unreadable") == ["buildkite"], out)
    check(".nvmrc selects the Node in a repo with no workflows", data["node"]["source"] == ".nvmrc" and data["node"]["used"] == "v22.1.0", data["node"])
    check("the NEAREST AGENTS.md's three prose commands are surfaced, not the root's or a sibling's",
          all(f"repo-declared check, run this: {c}" in out for c in ("node scripts/check.js --scope=local", "yarn test:jest x-pack/plugins/alerting",
                                                                      "node scripts/type_check.js"))
          and "scripts/other_check.js" not in out and "yarn test:jest --config x.js" not in out, out)
    check("the prose checks are in the JSON with their file and are never run",
          len(data["prose_checks"]) == 3 and all(p["from"].endswith("x-pack/plugins/alerting/AGENTS.md") for p in data["prose_checks"])
          and data["gates"] == [], data.get("prose_checks"))
    check("no runnable gate: NOT VERIFIED, exit 3, and --strict exits 2",
          "NOT VERIFIED" in out and data.get("verified") is False and code == 3 and verify(root, home, "--strict")[0] == 2, (code, out))


def test_prose_only_repo(tmp: Path) -> None:
    home = tmp / "home-prose"
    home.mkdir(parents=True)
    root = committed(tmp / "prose", {"AGENTS.md": "# Repo\n\nBefore a PR run `make check` and `make lint`.\n", "src/a.py": "a = 1\n"},
                     ("src/a.py", "a = 2\n"))
    code, out, data = verify(root, home)
    check("a CI-less repo surfaces the root AGENTS.md's commands, names no unreadable CI, and is not a pass",
          "run this: make check" in out and "run this: make lint" in out and "CI not readable" not in out
          and code == 3 and data.get("verified") is False, (code, out))
    code, out, _ = verify(committed(tmp / "bare", {"a.txt": "x\n"}), home)
    check("nothing declared at all is an error", code == 2 and "NOT VERIFIED" in out, (code, out))


def test_workflows_win(tmp: Path) -> None:
    """Workflows stay THE source: prose is not consulted, and unreadable CI falls through only without them."""
    root, home = fixture(tmp / "wf"), tmp / "home-wf"
    home.mkdir(parents=True)
    write(root, "AGENTS.md", "# Repo\n\nRun `make check`.\n")
    write(root, ".buildkite/pipeline.yml", "steps: []\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "prose and buildkite next to workflows")
    _, out, data = verify(root, home)
    check("with workflows nothing is unreadable and prose is not surfaced", "source: ci-workflow" in out and not data.get("ci_unreadable")
          and "repo-declared check" not in out and data.get("verified") is True, out)
    check("the JSON keeps schema_version 1 and every earlier key", data["schema_version"] == 1 and {"source", "gates", "node", "notes", "skipped"} <= set(data))
    root2 = fixture(tmp / "blk", workflow=False)
    write(root2, ".buildkite/pipeline.yml", "steps: []\n")
    write(root2, "AGENTS.md", "# R\n\n```gates\nunit: true\n```\n\nRun `make check`.\n")
    git(root2, "add", "-A")
    git(root2, "commit", "-q", "-m", "block and buildkite")
    code, out, data = verify(root2, home)
    check("unreadable CI falls through to the AGENTS.md gates block", "CI not readable here (buildkite)" in out and code == 0
          and data["source"] == "AGENTS.md gates block@main", (code, out))


def wf(trigger: str, extra: str = "") -> str:
    return f"on:{trigger}\njobs:\n  j:\n{extra}    steps:\n      - name: Gate\n        run: make gate\n"


EVALS_SHAPE = ("on:\n  pull_request:\n    branches: [main]\n  workflow_dispatch:\n    inputs:\n      provider:\n"
               "        type: choice\n        options: [openrouter, anthropic]\n")
TRIGGERS = {
    " push": True, " [push, pull_request]": True, "\n  pull_request:\n  push:\n    branches: [main]": True, "\n  - push": True,
    " pull_request_target": False, "\n  workflow_run:\n    workflows: [CI]": False, "\n  release:\n    types: [published]": False,
    " workflow_dispatch": False, " [push, workflow_dispatch]": True, " [push, pull_request, workflow_dispatch]": True,
    " [pull_request, pull_request_target]": False, "\n  push:\n    tags: ['v*']": False,
    "\n  push:\n    tags: ['v*']\n    branches: [main]": True, "\n  push:\n    tags: ['v*']\n  pull_request:": True,
}
PUBLISH_COMMANDS = ("npm publish", "pnpm publish", "yarn publish", "yarn npm publish", "docker push img:1", "gh release create v1",
                    "gh release upload v1 a.tgz", "gh release edit v1", "twine upload dist/*", "cargo publish", "gem push x.gem",
                    "git push origin HEAD", "npm ci && npm publish", "make build; docker push img", "make build\ngh release create v1",
                    "NPM_TOKEN=x npm publish --access public", "make a || git push")


def test_workflow_reading(tmp: Path) -> None:
    """Which workflows and steps become gates: CI triggers only, never a publish, never a gated job; setup lines dropped."""
    from crew.task.task_verify_env import is_partial
    from crew.task.task_verify_sources import block_gates, prose_commands, workflow_gates

    for trigger, mirrored in TRIGGERS.items():
        gates, skipped = workflow_gates({"a.yml": wf(trigger)})
        check(f"on:{trigger!r} {'is' if mirrored else 'is not'} mirrored, and a skip is recorded",
              bool(gates) == mirrored and (mirrored or any(s.startswith(("a.yml: workflow not mirrored (on: ", "a.yml: not CI (on: ")) for s in skipped)), gates)
    gates, skipped = workflow_gates({"evals.yml": EVALS_SHAPE + "jobs:\n  j:\n    steps:\n      - name: Gate\n        run: make gate\n"})
    check("a pull_request + workflow_dispatch workflow is mirrored", [g["command"] for g in gates] == ["make gate"] and not skipped, skipped)
    check("a workflow with no push or pull_request is named as not CI", workflow_gates({"nightly.yml": wf(" schedule")})[1] == ["nightly.yml: not CI (on: schedule)"])
    gates, skipped = workflow_gates({"a.yml": wf(" push", "    environment: production\n")})
    check("a job with environment: is skipped and says why", not gates and any("environment" in s for s in skipped), skipped)
    gated = wf(" push", "    if: startsWith(github.ref, 'refs/tags/')\n").replace("make gate", "npm publish")
    gates, skipped = workflow_gates({"a.yml": gated})
    check("a job-level if: is not mirrored and makes the run partial", gates == [] and "j: job with an if:, not mirrored" in skipped and is_partial(skipped))
    for command in PUBLISH_COMMANDS:
        step = "        run: |\n" + "".join(f"          {line}\n" for line in command.splitlines())
        gates, skipped = workflow_gates({"a.yml": f"on: push\njobs:\n  j:\n    steps:\n      - name: Ship\n{step}      - name: Unit\n        run: make unit\n"})
        check(f"`{command!r}` is never a gate and is recorded", [g["command"] for g in gates] == ["make unit"]
              and any(s.startswith("ship: runs a publish") for s in skipped) and is_partial(skipped), (gates, skipped))
    for command in ("npm run publish-docs", "echo npm publish", "git pushd", "docker pull img"):
        check(f"`{command}` is not mistaken for a publish", len(workflow_gates({"a.yml": wf(" push").replace("make gate", command)})[0]) == 1)
    gates, skipped = workflow_gates({"a.yml": "on: push\njobs:\n  j:\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm ci && npm test\n"
                                     "      - run: |\n          npm ci\n          npm run lint\n      - run: |\n          npm ci\n          pip install x\n"})
    check("`npm ci && npm test` keeps its gate, a block drops its leading setup lines, a setup-only step is skipped",
          [g["command"] for g in gates] == ["npm ci && npm test", "npm run lint"] and any("setup step" in s for s in skipped), (gates, skipped))
    text = "Run `npm test`.\n\n```gates\nunit: npm run check\n```\n\nThen `npm run lint`.\n"
    check("the gates block read is the block the prose commands leave out",
          [g["command"] for g in block_gates(text)] == ["npm run check"] and prose_commands(text) == ["npm test", "npm run lint"])
    root, home = fixture(tmp / "rel"), tmp / "home-rel"
    home.mkdir(parents=True)
    write(root, ".github/workflows/release.yml", "on:\n  push:\n    tags: ['v*']\njobs:\n  ship:\n    steps:\n      - run: npm publish\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "release workflow")
    _, out, _ = verify(root, home, "--list")
    check("--list names the workflows before any gate, never lists a publish, and names the release workflow",
          "workflows: .github/workflows/ci.yml" in out and ": npm publish" not in out
          and "unit-tests: sh check.sh" in out and ".github/workflows/release.yml: workflow not mirrored (on: push)" in out, out)


WORKFLOW_PARTIAL = ("on: push\njobs:\n  j:\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm ci\n"
                    "      - name: Cond\n        if: github.ref == 'x'\n        run: make deploy\n      - name: Unit\n        run: echo unit\n")


def test_partial_mirror_is_not_verified(tmp: Path) -> None:
    root, home = fixture(tmp / "pm"), tmp / "home-pm"
    home.mkdir(parents=True)
    write(root, ".github/workflows/ci.yml", WORKFLOW_PARTIAL)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "partial")
    code, out, data = verify(root, home)
    check("passing gates on a partial mirror are NOT VERIFIED (exit 3), counted, listed, said before any gate line",
          code == 3 and data.get("verified") is False and data.get("partial") is True and [g["exit"] for g in data["gates"]] == [0]
          and "skipped: 2 steps" in out and "not mirrored: 1 uses: steps" in out
          and out.index("NOT VERIFIED: partial mirror (1 steps skipped)") < out.index("exit="), (code, out))
    check("--strict makes it exit 2", verify(root, home, "--strict")[0] == 2)
    out_json = root.parent / "gates.json"
    cli("--repo", str(root), "--base", "main", "--out", str(out_json), "--background", home=home)
    waited = cli("--wait", str(out_json), "--timeout", "60", home=home)
    check("--wait agrees with the foreground path", waited.returncode == 3 and "NOT VERIFIED: partial mirror (1 steps skipped)" in waited.stdout, waited)
    write(root, ".github/workflows/ci.yml", WORKFLOW_PARTIAL.replace("echo unit", "exit 1"))
    git(root, "commit", "-qam", "failing")
    check("a failed gate still exits 1 on a partial mirror", verify(root, home)[0] == 1)


NOT_CI = {  # one CI file, the rest scheduled or dispatched by hand
    "ci.yml": "on:\n  pull_request:\n  push:\n    branches: [main]\njobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n"
              "      - run: npm ci\n      - name: Unit\n        run: echo unit\n",
    "generate.yml": "on:\n  schedule:\n    - cron: '0 8 * * *'\n  workflow_dispatch:\n    inputs:\n      dry_run:\n        type: boolean\n",
    "smoke.yml": "on:\n  schedule:\n    - cron: '15 6 * * *'\n",
    "migrate.yml": "on:\n  workflow_dispatch:\n",
    "hook.yml": "on:\n  repository_dispatch:\n    types: [deploy]\n",
}


def test_non_ci_workflows_are_not_partial(tmp: Path) -> None:
    root, home = fixture(tmp / "nc", workflow=False), tmp / "home-nc"
    home.mkdir(parents=True)
    for name, trigger in NOT_CI.items():
        write(root, f".github/workflows/{name}", trigger + ("" if name == "ci.yml" else "jobs:\n  run:\n    steps:\n      - name: Deploy\n        run: make deploy\n"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "workflows")
    code, out, data = verify(root, home)
    check("CI steps beside schedule- and dispatch-only workflows are verified (exit 0), each other workflow named not CI",
          code == 0 and data.get("verified") is True and data.get("partial") is False and [g.get("command") for g in data["gates"]] == ["echo unit"]
          and all(f".github/workflows/{name}: not CI (on: " in out for name in NOT_CI if name != "ci.yml"), (code, out))
    write(root, ".github/workflows/ci.yml", NOT_CI["ci.yml"] + "      - name: Cond\n        if: github.ref == 'x'\n        run: make it\n")
    git(root, "commit", "-qam", "conditional step")
    code, _, data = verify(root, home)
    check("a skipped step inside the CI workflow still makes the run partial", code == 3 and data.get("partial") is True)


def test_workflow_scalars_stay_as_written() -> None:
    """`on` stays a key and every scalar a string as written (`3.10` stays `3.10`); unreadable YAML is no workflow."""
    from crew.task.task_verify_sources import workflow

    doc = workflow("on:\n  push:\nenv:\n  PYTHON: 3.10\njobs:\n  j:\n    timeout-minutes: 5\n    continue-on-error: true\n")
    assert doc == {"on": {"push": ""}, "env": {"PYTHON": "3.10"}, "jobs": {"j": {"timeout-minutes": "5", "continue-on-error": "true"}}}
    assert workflow("jobs: [") == {}


REPORT = """## Implementation Report

**Tasks:** 2/2 passed

### Quality gates
```
knip exit=1
biome exit=0
```
- `knip` — {knip} — exit 1
- `biome` — {biome}

### Unverified claims
{claims}

### Report data
```json
{data}
```

### Files Changed
a.py
"""
REPORT_GATES = {"schema_version": 1, "state": "done", "gates": [
    {"name": "knip", "exit": 1, "command": "npm run knip"}, {"name": "biome", "exit": 0, "command": "npx biome ci ."}]}
REPORT_DATA = json.dumps({"schema_version": 1, "gates": [{"name": "knip", "exit": 1}, {"name": "biome", "exit": 0}]})
OLD_REPORT = "## Implementation Report\n\n**Tasks:** 1/1 passed\n\n### Quality gates\n- `npm test` — pass\n\n### Files Changed\na.py\n"


def report_text(knip: str = "fail", biome: str = "pass", claims: str = "- the hook runs — verify: `bash hook-test.sh`", data: str = REPORT_DATA) -> str:
    return REPORT.format(knip=knip, biome=biome, claims=claims, data=data)


# (case, report text, extra arguments, gates JSON or None, exit code, text the output must carry)
REPORT_CASES = (
    ("a verbatim copy with honest claims passes", report_text(), (), REPORT_GATES, 0, "report-check: ok"),
    ("a `pass` claim against exit=1 fails", report_text(knip="pass"), (), REPORT_GATES, 1, "contradicts exit=1"),
    ("a `fail` claim against exit=0 fails", report_text(biome="fail"), (), REPORT_GATES, 1, "biome: fail"),
    ("a `skipped` claim for a gate verify ran fails", report_text(biome="skipped"), (), REPORT_GATES, 1, "biome: skipped"),
    ("a copied line that differs from the JSON fails", report_text().replace("knip exit=1", "knip exit=0"), (), REPORT_GATES, 1,
     "report says exit=0, verify says exit=1"),
    ("a gate missing from the verbatim copy fails", report_text().replace("knip exit=1\n", ""), (), REPORT_GATES, 1, "gate knip (exit=1) is not copied"),
    ("Report data that disagrees with the JSON fails", report_text(data=REPORT_DATA.replace('"exit": 1', '"exit": 0')), (), REPORT_GATES, 1,
     "Report data gates differ"),
    *((f"a `{word}` claim is not one of pass, fail, skipped", report_text(knip=word), (), REPORT_GATES, 1, f"`{word}`")
      for word in ("passed", "clean", "ok", "green", "failed")),
    ("a gate with no claim line fails", report_text().replace("- `knip` — fail — exit 1\n", ""), (), REPORT_GATES, 1, "no claim line for gate knip"),
    ("two claim lines for one gate fail", report_text(biome="pass\n- `biome` — pass"), (), REPORT_GATES, 1, "2 claim lines for gate biome"),
    ("`none` is a valid Unverified claims section", report_text(claims="none"), (), REPORT_GATES, 0, ""),
    ("an unverified claim with no verify command fails", report_text(claims="- the hook runs under Cursor"), (), REPORT_GATES, 1, "without"),
    ("a strict check rejects a report with no new sections", OLD_REPORT, (), None, 1, "missing section: ### Unverified claims"),
    ("a Report data block that is not JSON fails", report_text(data="not json"), (), REPORT_GATES, 1, "schema_version"),
    ("a Report data block without schema_version 1 fails", report_text(data=json.dumps({"tasks": 1})), (), REPORT_GATES, 1, ""),
    ("an old report parses in lenient mode", OLD_REPORT, ("--lenient",), None, 0, ""),
    ("a gates JSON that exists is compared even in a lenient run", OLD_REPORT, ("--lenient",), REPORT_GATES, 1, "not copied"),
    ("claims about commands that are not gates are not compared", OLD_REPORT, ("--lenient",), {"gates": []}, 0, ""),
    ("--unverified prints the list capped at five", report_text(claims="\n".join(f"- claim {i} — verify: `cmd {i}`" for i in range(8))),
     ("--unverified", "5"), REPORT_GATES, 0, "+3 more"),
)


@pytest.mark.parametrize("case,text,extra,gates,code,needle", REPORT_CASES, ids=[case[0] for case in REPORT_CASES])
def test_report_check(case: str, text: str, extra: tuple[str, ...], gates: dict | None, code: int, needle: str, tmp: Path) -> None:
    """`crew-verify.py report-check`: a builder's REPORT.md may claim a gate only as the gates JSON recorded it."""
    (tmp / "REPORT.md").write_text(text, encoding="utf-8")
    arguments = [str(tmp / "REPORT.md"), *extra]
    if gates is not None:
        (tmp / "gates.json").write_text(json.dumps(gates), encoding="utf-8")
        arguments += ["--gates", str(tmp / "gates.json")]
    done = run_cli(CLI, "report-check", *arguments)
    assert done.returncode == code and needle in done.stdout + done.stderr, done.stdout + done.stderr


def test_report_parsers_on_an_old_report(tmp: Path) -> None:
    from crew.task import task_verify_report as rc
    check("every parser returns empty for an old report or plain prose", rc.sections(OLD_REPORT).get("Unverified claims") is None
          and rc.unverified_claims(OLD_REPORT) == [] and rc.report_data(OLD_REPORT) is None and rc.gate_exits(OLD_REPORT) == {}
          and rc.unverified_claims("just prose\n") == [] and rc.problems("x", None, True) == [] and rc.capped(OLD_REPORT, 5) == [])
    check("an unreadable gates file is not a crash", rc.load_gates(tmp / "missing.json") is None)
