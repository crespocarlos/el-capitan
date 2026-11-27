"""`crew-task.py ship` against a local origin and a stub `gh`: the happy path, each stop, and a re-run that resumes.

Every world is a bare repository served as `git@github.com:acme/widgets.git` through a fake ssh, a main checkout and
a worktree on the task's branch with one change; the spec's `## Tests` commands are chosen per test. Nothing reaches
GitHub: `gh pr create` prints a fixed PR URL, `pr list` answers it once `GH_OPEN` exists, `pr view` says CLOSED once
`GH_CLOSED` exists.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from cli_runner import load
from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / ".agent" / "tools" / "task" / "crew-task.py"
load(TASK)  # sets the import path the way the entry point does
import task_ship  # noqa: E402
from task_ship_checks import MAX_BYTES  # noqa: E402

PR = "https://github.com/acme/widgets/pull/7"
URL = "git@github.com:acme/widgets.git"
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
          "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_SSH_VARIANT": "simple"}
LISTED = json.dumps([{"url": PR, "headRepositoryOwner": {"login": "acme"}}])
GH_STUB = f"""#!/bin/sh
echo "$*" >> "$GH_CALLS"
case "$1 $2" in
  "pr create") echo "{PR}" ;;
  "pr list") if [ -f "$GH_OPEN" ]; then echo '{LISTED}'; else echo '[]'; fi ;;
  "pr view") if [ -f "$GH_CLOSED" ]; then echo CLOSED; else echo OPEN; fi ;;
  *) exit 1 ;;
esac
"""
FAKE_SSH = '#!/bin/sh\nfor arg; do last=$arg; done\ncd "$FAKE_SSH_ROOT" && exec sh -c "$last"\n'
TOKEN = "ghp_" + "a1" * 18


def executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def git(where: Path, *arguments: str, env: dict) -> str:
    return subprocess.run(["git", "-C", str(where), *arguments], check=True, capture_output=True, text=True,
                          env={**os.environ, **env}).stdout.strip()


def world(tmp: Path, *commands: str, boxes: str = "- [x] a") -> tuple[Path, Path, dict]:
    """(task dir, worktree, env): an IMPLEMENTING task on feat/x whose worktree changed a.txt and added new.txt."""
    origin, main, tree, task = tmp / "remote" / "acme" / "widgets.git", tmp / "main", tmp / "wt", tmp / "tasks" / "t1"
    executable(tmp / "bin" / "gh", GH_STUB)
    executable(tmp / "bin" / "ssh", FAKE_SSH)
    env = {**GIT_ID, "HOME": str(tmp), "PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
           "GIT_SSH": str(tmp / "bin" / "ssh"), "FAKE_SSH_ROOT": str(tmp / "remote"),
           "GH_CALLS": str(tmp / "calls"), "GH_OPEN": str(tmp / "open"), "GH_CLOSED": str(tmp / "closed")}
    origin.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", URL, str(main)], check=True, capture_output=True, env={**os.environ, **env})
    (main / "a.txt").write_text("one\n", encoding="utf-8")
    (main / ".gitignore").write_text("debug.log\n", encoding="utf-8")
    for arguments in (["add", "."], ["commit", "-q", "-m", "base"], ["push", "-q", "origin", "HEAD:main"],
                      ["remote", "set-head", "origin", "main"], ["worktree", "add", "-q", "-b", "feat/x", str(tree)]):
        git(main, *arguments, env=env)
    (tree / "a.txt").write_text("two\n", encoding="utf-8")
    (tree / "new.txt").write_text("new\n", encoding="utf-8")
    (tree / "debug.log").write_text("ignored\n", encoding="utf-8")
    task.mkdir(parents=True)
    layers = "".join(f"### {layer}\n- **Command**: `{command}`\n"
                     for layer, command in zip(("Unit", "Integration"), commands))
    (task / "SPEC.md").write_text(f"# T\n\n## Status\nIMPLEMENTING\n\n{boxes}\n\n## Tests\n{layers}", encoding="utf-8")
    meta = {"slug": "t1", "branch": "feat/x", "worktree": str(tree), "repo_remote_url": URL}
    (task / ".task-id").write_text(json.dumps(meta), encoding="utf-8")
    (tmp / "body.md").write_text("The body.\n", encoding="utf-8")
    return task, tree, env


def ship(tmp: Path, env: dict, *target: str, base: str = "main",
         cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run ship with the approved base and target, TASK_DIR or `--no-task` in `target`."""
    return cli(TASK, "ship", *target, "--title", "feat(x): ship it", "--body-file", str(tmp / "body.md"),
               "--base", base, "--repo", "acme/widgets", env=env, cwd=cwd)


def progress(task: Path) -> str:
    return (task / "PROGRESS.md").read_text(encoding="utf-8") if (task / "PROGRESS.md").is_file() else ""


def steps(task: Path, branch: str = "feat/x") -> list[str]:
    """The steps recorded for `branch`, in order: each entry is `SHIP: <branch> <step> [value]`."""
    entries = [line.split("SHIP: ", 1)[1].split() for line in progress(task).splitlines() if "SHIP: " in line]
    return [words[1] for words in entries if words[0] == branch]


def status(task: Path) -> str:
    return (task / "SPEC.md").read_text(encoding="utf-8").split("## Status\n", 1)[1].split("\n", 1)[0]


def calls(tmp: Path) -> str:
    return (tmp / "calls").read_text(encoding="utf-8") if (tmp / "calls").is_file() else ""


def test_happy_path_rerun_and_a_closed_pr(tmp: Path) -> None:
    task, tree, env = world(tmp, "test -f a.txt")
    result = ship(tmp, env, str(task))
    assert result.returncode == 0, result
    assert steps(task) == list(task_ship.STEPS) and status(task) == "DONE", (steps(task), result)
    pushed = git(tree, "ls-tree", "-r", "--name-only", "origin/feat/x", env=env).split()
    assert "new.txt" in pushed and "debug.log" not in pushed, pushed
    message = git(tree, "log", "-1", "--format=%B", "origin/feat/x", env=env)
    assert message.startswith("feat(x): ship it") and "Co-Authored-By: Claude" in message, message
    assert "pr create --draft --title feat(x): ship it" in calls(tmp), calls(tmp)
    assert "--base main --repo acme/widgets --head feat/x" in calls(tmp), calls(tmp)
    again = ship(tmp, env, str(task))
    assert again.returncode == 0 and again.stdout.count("already done") == len(task_ship.STEPS), again
    (tmp / "closed").touch()
    reopened = ship(tmp, env, str(task))
    assert reopened.returncode == 0 and calls(tmp).count("pr create") == 2, "a closed PR is opened again"


@pytest.mark.parametrize("label,base,branch,words", [
    ("a base other than the approved one", "develop", "feat/x", "--base develop disagrees with the default branch"),
    ("another branch", "main", "other", "not the task's branch feat/x"),
])
def test_refuses_before_staging(tmp: Path, label: str, base: str, branch: str, words: str) -> None:
    task, tree, env = world(tmp, "true")
    if branch != "feat/x":
        git(tree, "checkout", "-q", "-b", branch, env=env)
    result = ship(tmp, env, str(task), base=base)
    assert result.returncode == 2 and words in result.stderr and steps(task) == [], (label, result)


@pytest.mark.parametrize("name,size,words", [(".env.local", 8, "(looks like a secret)"),
                                             ("big.bin", MAX_BYTES + 1, "(larger than 1 MB)")])
def test_stops_on_a_risky_untracked_file(tmp: Path, name: str, size: int, words: str) -> None:
    task, tree, env = world(tmp, "true")
    (tree / name).write_bytes(b"x" * size)
    result = ship(tmp, env, str(task))
    assert result.returncode == 1 and f"{name} {words}" in result.stderr, result
    assert not git(tree, "diff", "--cached", "--name-only", env=env) and steps(task) == [], "nothing is staged"


def test_stops_on_a_token_in_a_tracked_file(tmp: Path) -> None:
    task, tree, env = world(tmp, "true")
    (tree / "a.txt").write_text(f"token = {TOKEN}\n", encoding="utf-8")
    result = ship(tmp, env, str(task))
    assert result.returncode == 1 and "a.txt contain a credential-like token" in result.stderr, result
    assert steps(task) == ["stage"], steps(task)


def test_stops_on_a_conflict(tmp: Path) -> None:
    task, _, env = world(tmp, "true")
    (tmp / "main" / "a.txt").write_text("three\n", encoding="utf-8")
    git(tmp / "main", "commit", "-q", "-am", "moved on", env=env)
    git(tmp / "main", "push", "-q", "origin", "HEAD:main", env=env)
    result = ship(tmp, env, str(task))
    assert result.returncode == 1 and "conflicts in: a.txt" in result.stderr, result
    assert steps(task) == ["stage", "commit"] and status(task) == "IMPLEMENTING", steps(task)


@pytest.mark.parametrize("label,commands,limits,words", [
    ("a hanging command", ("sleep 5",), {"COMMAND_LIMIT": 0.1}, "`sleep 5` ran past 0.1 s and was stopped"),
    # The total caps the first command below its own limit, whatever the runner's speed: `sleep 5` always outlasts it.
    ("the total limit", ("sleep 5", "true"), {"TOTAL_LIMIT": 0.3}, "`sleep 5` ran past 0.3 s"),
    ("a file the tests wrote", ("touch out.txt",), {}, "tests changed files: out.txt"),
])
def test_test_step_stops(tmp: Path, monkeypatch: pytest.MonkeyPatch, label: str, commands: tuple, limits: dict,
                         words: str) -> None:
    for constant, value in limits.items():
        monkeypatch.setattr(task_ship, constant, value)
    task, _, env = world(tmp, *commands)
    result = ship(tmp, env, str(task))
    assert result.returncode == 1 and words in result.stderr and "pr create" not in calls(tmp), (label, result)


def test_failing_tests_stop_and_a_rerun_resumes_reusing_the_open_pr(tmp: Path) -> None:
    marker = tmp / "broken"
    marker.touch()
    task, tree, env = world(tmp, f'test ! -e {marker} && test -z "$CLAUDE_JOB_DIR$CLAUDECODE"')
    env.update(CLAUDE_JOB_DIR=str(tmp), CLAUDECODE="1")
    result = ship(tmp, env, str(task))
    assert result.returncode == 1 and "failed with exit 1" in result.stderr, result
    assert steps(task) == ["stage", "commit", "merge"] and "pr " not in calls(tmp), steps(task)
    marker.unlink()
    (tmp / "open").touch()
    resumed = ship(tmp, env, str(task))
    assert resumed.returncode == 0 and status(task) == "DONE" and "pr create" not in calls(tmp), resumed
    assert all(f"{step} already done" in resumed.stdout for step in ("stage", "commit", "merge")), resumed.stdout
    assert git(tree, "rev-list", "--count", "origin/main..HEAD", env=env) == "1", "one commit, never amended"


def test_no_task_ships_the_current_checkout(tmp: Path) -> None:
    _, tree, env = world(tmp, "true")
    result = ship(tmp, env, "--no-task", cwd=tree)
    assert result.returncode == 0 and "pr create" in calls(tmp) and PR in result.stdout, result


def test_phases_keep_the_task_implementing_and_start_fresh_on_a_new_branch(tmp: Path) -> None:
    task, tree, env = world(tmp, "true", boxes="- [x] phase one\n- [ ] phase two")
    refused = ship(tmp, env, str(task))
    assert refused.returncode == 2 and "1 unchecked criteria" in refused.stderr, "plain ship needs every box"
    first = ship(tmp, env, str(task), "--phase")
    assert first.returncode == 0 and status(task) == "IMPLEMENTING", first
    assert f"PR: {PR}" in progress(task) and steps(task) == list(task_ship.STEPS[:-1]), progress(task)
    git(tree, "checkout", "-q", "-b", "feat/y", env=env)
    (tree / "b.txt").write_text("phase two\n", encoding="utf-8")
    meta = json.loads((task / ".task-id").read_text(encoding="utf-8"))
    (task / ".task-id").write_text(json.dumps({**meta, "branch": "feat/y"}), encoding="utf-8")
    second = ship(tmp, env, str(task), "--phase")
    assert second.returncode == 0 and "already done" not in second.stdout, second
    assert steps(task, "feat/y") == list(task_ship.STEPS[:-1]) and calls(tmp).count("pr create") == 2, progress(task)
