#!/usr/bin/env python3
"""Every cataloged command runs the way an installed one does: through a symlink, from elsewhere.

`install.sh` links each `kind: command` entry of `src/crew/tools.json` into `~/.agent/bin`, and
callers run the link from whatever repository they are in. Each command therefore runs here through
a symlink in a temporary bin directory, from a cwd outside this repository, with a throwaway HOME,
with a read-only invocation from `READS` (`--help` is checked by `test_command_names.py`). A command
passes when the exit code is one its table entry expects and stderr carries no traceback (an import that only works from
the source tree fails here). Source-only scripts are sourced by bash instead of executed.

The interpreter is the `python3` first on PATH, the one each command's shebang resolves to.
"""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cli_runner import launcher

# An install, then every command through its link (each run allowed 120 s): more than the suite's 60 s.
pytestmark = pytest.mark.timeout(300)
ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "src" / "crew"
SOURCE_ONLY = {"task-env.sh", "crew-diff.sh"}
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}

# name -> (read-only arguments, accepted exit codes). `{repo}`, `{task}`, `{tasks}`, `{diff}`,
# `{tmp}` and `{root}` are filled in per run. A command that needs live infrastructure (a nightshift
# server, Elasticsearch) gets a subcommand `--help` or the documented "unavailable" exit instead.
READS = {
    "crew-agent-context.py": (["{repo}/README.md"], {0}),
    "crew-lint.py": (["--json", "--root", "{root}"], {0, 1}),
    "crew-ls.py": (["--json", "--tasks-dir", "{tasks}"], {0}),
    "crew-doctor.py": (["--offline"], {1}),  # the throwaway HOME has no install: problems, exit 1
    # Plans only: a reply mutates GitHub solely with --execute.
    "crew-pr-actions.py": (["reply", "--repo", "o/r", "--pr", "1", "--thread-id", "T",
                            "--comment-id", "C", "--body", "b"], {0}),
    "crew-review-findings.py": (["select", "--mode", "self"], {0}),
    "crew-review-hunks.py": (["{diff}", "--out", "{tmp}/hunks"], {0}),
    "crew-assemble-packages.py": (["{task}"], {2}),
    "crew-nightshift-e2e.py": (["worktrees", "--help"], {0}),
    "crew-evals-compare.py": (["runs", "--help"], {0}),
    "crew-evals-inspect.py": (["latest"], {2}),
    "crew-metric.py": (["{task}", "probe=1"], {0}),
    "crew-progress.py": (["{task}", "IMPLEMENTING → REVIEW"], {0}),
    "crew-verify.py": (["report-check", "{task}/REPORT.md"], {0, 1}),
    "crew-task.py": (["normalize-status", "--tasks-dir", "{tasks}"], {0}),
    "crew-mem.py": (["list", "--json", "--limit", "1"], {0}),
    "crew-inbox.py": (["--json"], {0}),
    "crew-resolve-task-dir.py": (["--json"], {0}),
    "crew-task-context.py": (["--json", "--remote", "https://example.invalid/none.git",
                              "--branch", "none"], {0}),
    "crew-worktree.py": (["--list"], {0}),
    "crew-repo-info.py": (["--json"], {0}),
    "crew-hook.py": (["--help"], {0}),
    "crew-default-branch.sh": ([], {0}),
    "task-env.sh": ([], {0}),
    "crew-diff.sh": (["--name-only"], {0}),
}

SAMPLE_DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n one\n+two\n"


def catalog() -> list[dict]:
    data = json.loads((TOOLS / "tools.json").read_text(encoding="utf-8"))
    return [entry for section in ("tools", "scripts") for entry in data.get(section, [])
            if entry.get("kind") == "command"]


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, **GIT_ID})


def workspace(tmp: Path) -> dict[str, str]:
    """A repository with two commits and a local origin, a task directory, and a diff file."""
    origin, repo = tmp / "origin.git", tmp / "repo"
    git("init", "-q", "--bare", str(origin), cwd=tmp)
    git("init", "-q", "-b", "main", str(repo), cwd=tmp)
    (repo / "AGENTS.md").write_text("# Guidance\n", encoding="utf-8")
    for name in ("README.md", "b.txt"):
        (repo / name).write_text(name + "\n", encoding="utf-8")
        git("add", name, cwd=repo)
        git("commit", "-qm", name, cwd=repo)
    git("remote", "add", "origin", str(origin), cwd=repo)
    git("push", "-q", "origin", "main", cwd=repo)
    (repo / "b.txt").write_text("changed\n", encoding="utf-8")  # pending work for crew-diff.sh
    task = tmp / "tasks" / "T-1"
    task.mkdir(parents=True)
    (task / "REPORT.md").write_text("## Implementation Report\n", encoding="utf-8")
    (tmp / "sample.diff").write_text(SAMPLE_DIFF, encoding="utf-8")
    return {"repo": str(repo), "task": str(task), "tasks": str(task.parent),
            "diff": str(tmp / "sample.diff"), "tmp": str(tmp), "root": str(ROOT)}


def link_commands(entries: list[dict], bin_dir: Path) -> None:
    bin_dir.mkdir()
    for entry in entries:
        python = entry["name"].endswith(".py")
        (bin_dir / entry["name"]).symlink_to(launcher(entry["name"]) if python else TOOLS / entry["dir"] / entry["name"])


def invoke(link: Path, args: list[str], cwd: str, env: dict) -> subprocess.CompletedProcess:
    if link.name in SOURCE_ONLY:
        argv = ["bash", "-c", 'f=$1; shift; . "$f" "$@"', "bash", str(link), *args]
    else:
        argv = [str(link), *args]
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=120)


def verdict(name: str, label: str, done: subprocess.CompletedProcess, accepted: set) -> str:
    if done.returncode in accepted and "Traceback" not in done.stderr:
        return ""
    return (f"{name} {label}: exit {done.returncode} (accepted {sorted(accepted)}); "
            f"stderr={done.stderr[-400:]!r}")


def environment(tmp: Path) -> dict:
    env = {**os.environ, **GIT_ID, "HOME": str(tmp / "home"),
           "CREW_MEMORY_DIR": str(tmp / "memory"), "ES_URL": "http://127.0.0.1:9",
           "PYTHONDONTWRITEBYTECODE": "1"}
    for key in ("CREW_TASK_DIR", "CREW_TASK_STATE", "CREW_JOURNAL_DIR"):
        env.pop(key, None)
    (tmp / "home").mkdir()
    return env


def run_all(tmp: Path) -> list[str]:
    entries = catalog()
    failures = [f"{e['name']}: no read-only invocation in READS" for e in entries
                if e["name"] not in READS]
    failures += [f"{name}: in READS but not a cataloged command" for name in
                 sorted(set(READS) - {e["name"] for e in entries})]
    places, env = workspace(tmp), environment(tmp)
    link_commands(entries, tmp / "bin")
    mem = invoke(tmp / "bin" / "crew-mem.py", ["init"], places["repo"], env)
    failures.append(verdict("crew-mem.py", "init", mem, {0}))
    jobs = []
    for entry in entries:
        args, accepted = READS.get(entry["name"], ([], {0}))
        jobs.append((entry["name"], args, [arg.format(**places) for arg in args], accepted))
    def read(job: tuple) -> str:
        name, args, filled, accepted = job
        done = invoke(tmp / "bin" / name, filled, places["repo"], env)
        return verdict(name, " ".join(["read", *args]), done, accepted)

    with ThreadPoolExecutor(max_workers=8) as pool:
        failures += pool.map(read, jobs)
    return [failure for failure in failures if failure]


def test_every_command_runs_through_its_link(tmp: Path) -> None:
    failures = run_all(tmp.resolve())
    assert not failures, "\n".join(failures)
