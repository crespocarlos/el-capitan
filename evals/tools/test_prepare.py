"""The `prepare` commands: one call sets a stage up, on a temporary repository, with no network.

One test per command (review `prepare` in self mode, `prepare-implement`, `prepare-spec`) plus the PR-mode case,
where a stub `gh` first on PATH answers `pr view`, `pr diff` and GraphQL and logs each call, so the test sees the
head files fetched in exactly one GraphQL call. HOME is a temporary directory, so the memory store, the templates
and the review directories of the real owner are never touched.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from cli_runner import run as cli
from task_fixture import record_status

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = ROOT / ".agent" / "tools" / "review" / "crew-review-findings.py"
ASSEMBLE = ROOT / ".agent" / "tools" / "review" / "crew-assemble-packages.py"
TASK = ROOT / ".agent" / "tools" / "task" / "crew-task.py"

# `GH_MOVE` set: the second `pr view` reports another head, as a push during `prepare` would.
GH_STUB = r'''
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["GH_LOG"], "a") as log:
    log.write(json.dumps(argv) + "\n")
files = json.load(open(os.environ["GH_FILES"]))
if argv[:2] == ["pr", "view"]:
    views = sum(1 for line in open(os.environ["GH_LOG"]) if line.startswith('["pr", "view"'))
    sha = "b" * 40 if os.environ.get("GH_MOVE") and views > 1 else "a" * 40
    print(json.dumps({"headRefOid": sha, "headRepository": {"name": "widgets"},
                      "headRepositoryOwner": {"login": "acme"}}))
elif argv[:2] == ["pr", "diff"]:
    for path in files:
        sys.stdout.write(f"{path}\n" if "--name-only" in argv else
                         f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n")
elif argv[:2] == ["api", "graphql"]:
    pairs = dict(item.split("=", 1) for item in argv[2:] if "=" in item and item[0] != "-")
    repo = {}
    for key, value in pairs.items():
        if key.startswith("e"):
            path = value.split(":", 1)[1]
            body = files.get(path)
            repo["f" + key[1:]] = None if body is None else (
                {"byteSize": 9, "isBinary": True, "isTruncated": False, "text": None} if body == "<binary>"
                else {"byteSize": len(body), "isBinary": False, "isTruncated": False, "text": body})
    print(json.dumps({"data": {"repository": repo}}))
else:
    sys.stderr.write("gh stub: unexpected call\n")
    sys.exit(1)
'''


def git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True).stdout


def repository(tmp: Path) -> Path:
    """A checkout on `main` with an `origin` holding it, guidance at the root, and a prompt file."""
    origin, repo = tmp / "origin.git", tmp / "widgets"
    git(tmp, "init", "-q", "--bare", str(origin))
    git(tmp, "init", "-q", "-b", "main", str(repo))
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "remote", "add", "origin", str(origin))
    (repo / "AGENTS.md").write_text("# Guide\n\nKeep it small.\n\n## Tests\nrun pytest\n\n"
                                    "## Persistent memory\nrecall\n")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("a\nb\n")
    (repo / ".cursor" / "agents").mkdir(parents=True)
    (repo / ".cursor" / "agents" / "x.md").write_text("prompt\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "remote", "set-head", "origin", "main")
    return repo


def environment(tmp: Path, files: dict | None = None) -> dict:
    """HOME under `tmp` and a stub `gh` first on PATH (it fails every call it does not know)."""
    stub = tmp / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "gh_stub.py").write_text(GH_STUB)
    (stub / "gh").write_text(f'#!/bin/sh\nexec {sys.executable} "{stub / "gh_stub.py"}" "$@"\n')
    (stub / "gh").chmod(0o755)
    (tmp / "files.json").write_text(json.dumps(files or {}))
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    return {"HOME": str(home), "PATH": f"{stub}:/usr/bin:/bin", "GH_LOG": str(tmp / "gh.log"),
            "GH_FILES": str(tmp / "files.json"), "CREW_MEMORY_DIR": None, "GH_MOVE": None}


def own_temp(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review directories under `tmp`: the commands run in this process, where `tempfile` caches its directory."""
    (tmp / "t").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp / "t"))


def test_review_prepare_self_writes_every_input_and_holds_the_questions(tmp: Path, monkeypatch) -> None:
    repo = repository(tmp)
    git(repo, "switch", "-qc", "feat/parent")
    (repo / "src" / "parent.py").write_text("from the parent branch\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "parent")
    git(repo, "switch", "-qc", "feat/x")
    (repo / "src" / "a.py").write_text("a\nB\n")
    (repo / "src" / "new.py").write_text("untracked\n")
    (repo / ".env.local").write_text("TOKEN=x\n")
    (repo / "dump.log").write_text("x" * (256 * 1024 + 1))
    (repo / ".cursor" / "agents" / "x.md").write_text("prompt 2\n")
    env = environment(tmp)
    own_temp(tmp, monkeypatch)
    done = cli(FINDINGS, "prepare", "--mode", "self", "--base", "feat/parent", env=env, cwd=repo)
    assert done.returncode == 0, done.stderr
    review, line = done.stdout.splitlines()
    review = Path(review)
    assert (review / "paths.txt").read_text().split() == [".cursor/agents/x.md", "src/a.py", "src/new.py"]
    assert "untracked files not reviewed" in line and ".env.local, dump.log" in line and "git add -N" in line
    for name in ("diff.patch", "hunks.json", "hunks.index.md", "package.diff", "manifest.json", "run.json"):
        assert (review / name).is_file(), name
    assert str(repo.resolve() / "AGENTS.md") in json.loads((review / "agent-context.json").read_text())["files"]
    config = json.loads((review / "assemble.json").read_text())
    assert config["selected"] == ["adversarial", "code-quality", "prompt-quality"]
    assert config["prompt_files"] == [".cursor/agents/x.md"] and "Size gate: full diff" in config["size_gate"]
    assert "personas adversarial code-quality prompt-quality" in line and "TODO(prepare)" in line
    whole = cli(FINDINGS, "prepare", "--mode", "self", env=env, cwd=repo)
    assert "src/parent.py" in (Path(whole.stdout.splitlines()[0]) / "paths.txt").read_text()
    refused = cli(ASSEMBLE, str(review), env=env)
    assert refused.returncode == 2 and "TODO(prepare)" in refused.stderr
    quoting = "Does a TODO(prepare) question left in assemble.json stop assembly?"
    config["questions"] = {p: [quoting, "Who reads src/a.py?"] for p in config["questions"]}
    (review / "assemble.json").write_text(json.dumps(config))
    assert cli(ASSEMBLE, str(review), env=env).returncode == 0
    personas = ["--personas", *config["selected"]]
    assert cli(FINDINGS, "check-packages", "--review-dir", str(review), *personas, env=env).returncode == 0
    package = review / "adversarial.in.md"
    package.write_text(package.read_text().replace("Who reads src/a.py?", "TODO(prepare) question 2 for it"))
    held = cli(FINDINGS, "check-packages", "--review-dir", str(review), *personas, env=env)
    assert held.returncode == 1 and "TODO(prepare)" in held.stderr
    nothing = tmp / "clean"
    git(tmp, "clone", "-q", str(tmp / "origin.git"), str(nothing))
    empty = cli(FINDINGS, "prepare", "--mode", "changes", env=env, cwd=nothing)
    assert empty.returncode == 1 and "prepare: diff:" in empty.stderr


def test_review_prepare_pr_fetches_every_head_file_in_one_gh_call(tmp: Path, monkeypatch) -> None:
    files = {"src/a.py": "a\nnew\n", "index.json": '{"own": true}\n', "img/logo.png": "<binary>", "gone.txt": None}
    env = environment(tmp, files)
    own_temp(tmp, monkeypatch)
    task = tmp / "task"
    task.mkdir()
    (task / "SPEC.md").write_text("# Unrelated active task\n\n## Status\nIMPLEMENTING\n")
    done = cli(FINDINGS, "prepare", "--mode", "PR", "--pr", "7", "--repo", "acme/widgets", "--task-dir", str(task),
               env=env, cwd=tmp)
    assert done.returncode == 0, done.stderr
    review = Path(done.stdout.splitlines()[0])
    calls = [json.loads(line) for line in (tmp / "gh.log").read_text().splitlines()]
    assert [call[:2] for call in calls].count(["api", "graphql"]) == 1 and len(calls) == 4, calls
    assert not str(review).startswith(str(task)) and not (task / "review").exists()
    head = review / "head"
    assert (head / "files" / "src" / "a.py").read_text() == "a\nnew\n"
    assert (head / "files" / "index.json").read_text() == '{"own": true}\n'
    index = json.loads((head / "index.json").read_text())["files"]
    assert index["img/logo.png"]["status"] == "binary" and index["gone.txt"]["status"] == "absent"
    config = json.loads((review / "assemble.json").read_text())
    assert config["mode_kind"] == "pr" and "prompt_files" not in config and "repo" not in config
    assert "4 files at aaaaaaa in 1 call" in done.stdout
    (tmp / "gh.log").unlink()
    moved = cli(FINDINGS, "prepare", "--mode", "pr", "--pr", "7", "--repo", "acme/widgets",
                env={**env, "GH_MOVE": "1"}, cwd=tmp)
    assert moved.returncode == 2 and "the PR moved" in moved.stderr
    resolver = cli(ROOT / ".agent" / "tools" / "review" / "crew-pr-actions.py", "head", "--pr", "7", "--repo",
                   "acme/widgets", "--out", str(tmp / "resolver"), env=env, cwd=tmp)
    assert resolver.returncode == 0 and (tmp / "resolver" / "files" / "index.json").is_file(), resolver.stderr


def spec_with(task: Path, tasks: str, note: str) -> Path:
    task.mkdir(parents=True, exist_ok=True)
    (task / "SPEC.md").write_text("# Widgets\n\n## Branch: feat/widgets\n\n## Status\nAPPROVED\n\n"
                                  f"## Tasks\n{tasks}\n\n{note}\n\n## Hints\n`src/a.py` uses atomic_write.\n")
    (task / ".task-id").write_text(json.dumps({"slug": task.name, "branch": "main"}))
    record_status(task, "APPROVED")
    return task


def test_prepare_implement_cuts_the_branch_and_writes_the_builder_prompts(tmp: Path) -> None:
    repo = repository(tmp)
    env = environment(tmp)
    tasks = tmp / "home" / ".agent" / "tasks"
    labelled = "- [x] T0: done.\n" + "\n".join(f"- [ ] T{n}: step {n}.\n  - **Verify:** `true`" for n in range(1, 10))
    task = spec_with(tasks / "T1", labelled, "> Tasks 7 and 8 are atomic — commit together.")
    asked = cli(TASK, "prepare-implement", str(task), env=env, cwd=repo)
    assert asked.returncode == 1 and "prepare-implement: where:" in asked.stderr
    done = cli(TASK, "prepare-implement", str(task), "--where", "here", env=env, cwd=repo)
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.splitlines()[0]) == repo.resolve()
    assert git(repo, "branch", "--show-current").strip() == "feat/widgets"
    assert json.loads((task / ".task-id").read_text())["branch"] == "feat/widgets"
    assert "IMPLEMENTING" in (task / "SPEC.md").read_text() and (task / "BASELINE.diff").is_file()
    assert not (repo / ".crew-worker.lock").exists()
    prompts = sorted(p.name for p in (task / "dispatch").iterdir())
    assert prompts == ["builder.1-6.md", "builder.7-9.md"], prompts
    first = (task / "dispatch" / "builder.1-6.md").read_text()
    assert first.startswith(f"crew-task: {task.resolve()}\nTASK_RANGE: 1-6\n")
    guidance = first[first.index("## Project guidance"):first.index("## Tasks")]
    assert "run pytest" in guidance and "recall" in guidance, "under the cap, nothing is dropped"
    assert "Guidance collected for: ." in guidance, "no task names a path: the root's guidance, said so"
    second = (task / "dispatch" / "builder.7-9.md").read_text()
    assert "TASK_RANGE: 7-9 final" in second and "T7: step 7" in second and "T8: step 8" in second
    other = cli(TASK, "prepare-implement", str(task), "--branch", "feat/other", env=env, cwd=repo)
    assert other.returncode == 1 and "feat/widgets" in other.stderr and "feat/other" in other.stderr
    git(repo, "switch", "-q", "main")
    ranged = spec_with(tasks / "T2", labelled.replace("[x] T0", "[ ] T0"), "> Tasks 5-7 are atomic.")
    assert cli(TASK, "prepare-implement", str(ranged), "--branch", "feat/ranged", env=env, cwd=repo).returncode == 0
    assert sorted(p.name for p in (ranged / "dispatch").iterdir()) == ["builder.0-7.md", "builder.8-9.md"]
    git(repo, "switch", "-q", "main")
    vague = spec_with(tasks / "T3", labelled, "> The schema tasks are atomic.")
    refused = cli(TASK, "prepare-implement", str(vague), "--branch", "feat/vague", env=env, cwd=repo)
    assert refused.returncode == 1 and "The schema tasks are atomic" in refused.stderr


def test_prepare_spec_creates_the_task_and_the_explorer_prompt(tmp: Path) -> None:
    repo = repository(tmp)
    env = environment(tmp)
    agent = tmp / "home" / ".agent"
    agent.mkdir(parents=True)
    (agent / "_SPEC_TEMPLATE.md").write_text("# Spec: [title]\n")
    done = cli(TASK, "prepare-spec", "--slug", "add-retry", "--paths", "src/a.py", env=env, cwd=repo)
    assert done.returncode == 0, done.stderr
    task = Path(done.stdout.splitlines()[0])
    assert task.parent == agent / "tasks" and not (task / "SPEC.md").exists()
    identity = json.loads((task / ".task-id").read_text())
    assert identity["slug"] == "add-retry" and identity["branch"] == "main" and identity["uuid"] == task.name
    (prompt,) = task.glob("spec-agents/*/specwriter-explorer.prompt.md")
    text = prompt.read_text()
    nonce = (prompt.parent / "specwriter-explorer.expect").read_text().strip()
    assert text.splitlines()[0].endswith(f" specwriter-explorer {nonce}") and f"crew-task: {task}" in text
    assert "Keep it small." in text and "TODO(prepare)" in text and "_SPEC_TEMPLATE.md" in done.stdout
    missing = cli(TASK, "prepare-spec", "--slug", "x", "--bug", env=env, cwd=repo)
    assert missing.returncode == 2 and "prepare-spec: template:" in missing.stderr
