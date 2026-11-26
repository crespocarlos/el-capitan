#!/usr/bin/env python3
"""Where `crew implement` runs the worker: here by default, in a worktree on request; the lock works.

el-capitan is project-agnostic, so a worktree is opt-in: the default is a branch off the default
branch in the current checkout. The skill is prose, so the contract is its text: the default and the
two ways to opt in (the user asks, or `AGENTS.md` says `worktree: true`), the question asked at most
once per repo, the orchestrator running its own git as `git -C <tree>`, and the builder exporting
`CREW_WORKER_TASK` so the guard lets it change its own branch. The pieces with code are exercised on
a real repository: the lock round trip (`crew-progress.py lock`) and the choice and its record
(`crew-progress.py worktree pref|record`).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".cursor" / "skills" / "crew-implement" / "SKILL.md"
REFERENCE = ROOT / ".cursor" / "skills" / "crew-implement" / "references" / "worker-dispatch.md"
BUILDER = ROOT / ".cursor" / "agents" / "crew-builder.md"
PROGRESS = ROOT / ".agent" / "tools" / "task" / "crew-progress.py"
FAILURES: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        FAILURES.append(name)


def progress(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(PROGRESS), *arguments], text=True, capture_output=True)


def lock_round_trip() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tree = Path(raw) / "tree"
        subprocess.run(["git", "init", "-q", str(tree)], check=True)
        lock = tree / ".crew-worker.lock"
        written = progress("lock", "write", str(tree), "--task", "T-123")
        check("lock write exits 0", written.returncode == 0)
        body = lock.read_text(encoding="utf-8") if lock.is_file() else ""
        check("lock holds the task id", "task=T-123" in body.splitlines())
        check("lock holds a start timestamp", any(line.startswith("started=") and line[8:].isdigit()
                                                  for line in body.splitlines()))
        status = subprocess.run(["git", "-C", str(tree), "status", "--porcelain"], text=True,
                                capture_output=True).stdout
        check("lock is excluded through .git/info/exclude", ".crew-worker.lock" not in status)
        progress("lock", "write", str(tree), "--task", "T-123")
        exclude = (tree / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        check("exclude line is written once", exclude.count(".crew-worker.lock") == 1)
        removed = progress("lock", "remove", str(tree))
        check("lock remove exits 0 and deletes the file", removed.returncode == 0 and not lock.exists())
        check("removing an absent lock is not an error", progress("lock", "remove", str(tree)).returncode == 0)


def pref(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return progress("worktree", *arguments, "--repo", str(repo))


def git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True)


def worktree_choice() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, task = Path(raw) / "repo", Path(raw) / "task"
        repo.mkdir()
        task.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (task / "PROGRESS.md").write_text("", encoding="utf-8")
        check("a repo that never answered gets `ask`", pref(repo, "pref").stdout.strip() == "ask")
        recorded = progress("worktree", "record", "here", str(task), "--repo", str(repo))
        marker = repo / ".git" / "crew-worktree"
        check("recording `here` exits 0 and writes the per-repo marker", recorded.returncode == 0
              and marker.is_file() and marker.read_text(encoding="utf-8").strip() == "here")
        check("the answer is also a WORKTREE line in the task's PROGRESS.md",
              "WORKTREE: here" in (task / "PROGRESS.md").read_text(encoding="utf-8"))
        check("the recorded answer is reused, never asked again", pref(repo, "pref").stdout.strip() == "here")
        progress("worktree", "record", "worktree", str(task), "--repo", str(repo))
        check("a second record changes nothing (asked at most once)",
              marker.read_text(encoding="utf-8").strip() == "here"
              and (task / "PROGRESS.md").read_text(encoding="utf-8").count("WORKTREE:") == 1)
        (repo / "AGENTS.md").write_text("# Repo\n\nworktree: true\n", encoding="utf-8")
        check("`worktree: true` in AGENTS.md wins over a recorded `here`", pref(repo, "pref").stdout.strip() == "worktree")
        check("--json names the source", '"source": "agents"' in pref(repo, "pref", "--json").stdout)
        (repo / "AGENTS.md").write_text("# Repo\n\nworktree: false\n", encoding="utf-8")
        check("`worktree: false` means here", pref(repo, "pref").stdout.strip() == "here")
        marker.unlink()
        (repo / "AGENTS.md").write_text("# Repo\n\nNo setting here.\n", encoding="utf-8")
        check("no setting and no record is `ask` again", pref(repo, "pref").stdout.strip() == "ask")
        check("an answer that is neither is refused", progress("worktree", "record", "maybe", str(task), "--repo", str(repo)).returncode == 2)


def tree_check() -> None:
    """`worktree check`: ok on a clean default branch, on-feature-branch (4) when already off it, dirty (5) otherwise."""
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw) / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")

        def run(*extra: str) -> subprocess.CompletedProcess[str]:
            return progress("worktree", "check", str(repo), *extra)

        done = run()
        check("a clean default branch is `ok`, exit 0", done.stdout.strip() == "ok" and done.returncode == 0)
        (repo / "mine.txt").write_text("x", encoding="utf-8")
        done = run()
        check("an uncommitted file is `dirty`, exit 5", done.stdout.strip() == "dirty" and done.returncode == 5)
        (repo / ".crew-worker.lock").write_text("task=T\n", encoding="utf-8")
        (repo / "mine.txt").unlink()
        check("the worker lock is the task's own file, so still `ok`", run().stdout.strip() == "ok")
        (repo / "tasks").mkdir()
        (repo / "tasks" / "SPEC.md").write_text("spec", encoding="utf-8")
        check("files under --task-dir are the task's own", run("--task-dir", str(repo / "tasks")).returncode == 0)
        check("without --task-dir the same file is `dirty`", run().returncode == 5)
        (repo / "tasks" / "SPEC.md").unlink()
        git(repo, "switch", "-q", "-c", "feat/x")
        (repo / "wip.txt").write_text("x", encoding="utf-8")
        done = run("--json")
        check("a non-default branch is used as-is, even when dirty: exit 4",
              done.returncode == 4 and '"state": "on-feature-branch"' in done.stdout and "feat/x" in done.stdout)
        check("a path that is not a repo is exit 2", progress("worktree", "check", str(Path(raw) / "none")).returncode == 2)


def main() -> int:
    tree_check()
    skill = SKILL.read_text(encoding="utf-8")
    reference = REFERENCE.read_text(encoding="utf-8") if REFERENCE.is_file() else ""
    combined = skill + reference
    check("the worktree is no longer unconditional", "always runs in a worktree" not in skill
          and "Always create (or reuse) a worktree" not in skill and "if the answer is the main tree, stop" not in skill)
    step4 = skill.split("### Step 4")[1].split("### Step 5")[0].split("Then **bootstrap")[0]
    check("Step 4 says only: run `worktree pref` and follow worker-dispatch.md",
          "crew-progress.py worktree pref" in step4 and "references/worker-dispatch.md" in step4 and len(step4) < 400)
    check("default: a branch off the default branch in the current checkout, no worktree",
          "current checkout" in reference and "no worktree" in reference)
    check("a worktree only when the user asks or AGENTS.md sets `worktree: true`",
          "user asks" in reference and "`worktree: true`" in reference)
    check("the question is asked at most once per repo and recorded",
          "once per repo" in combined and "worktree pref" in combined and "worktree record" in combined and "PROGRESS.md" in combined)
    check("the dispatch reference mandates git -C <tree> for the orchestrator", "git -C <tree>" in reference)
    check("the branch comes from `## Branch:` with a derived fallback in the reference", "## Branch:" in reference and "<=50" in reference)
    check("the dispatch reference runs `worktree check` and names its three answers",
          "crew-progress.py worktree check" in reference and all(w in reference for w in ("on-feature-branch", "dirty", "ok")))
    check("the dispatch reference: a non-default branch is used as-is, a dirty tree stops with one question",
          "as-is" in reference and "ask once" in reference)
    check("`dirty` names its options and exit 2 stops with stderr",
          all(w in reference for w in ("commit them", "stash them", "use a worktree", "or stop")) and "exit 2" in reference
          and "show its stderr and stop" in reference)
    check("WORK_DIR is assigned before `worktree check` runs on it",
          0 <= reference.find("WORK_DIR=$(~/.agent/bin/crew-repo-info.py") < reference.find("crew-progress.py worktree check \"$WORK_DIR\""))
    ok_block = reference.split("- `ok` (exit 0)")[1].split("```bash")[1].split("```")[0]
    check("the `ok` block keeps only fetch and switch", "WORK_DIR=" not in ok_block and "fetch" in ok_block and "switch" in ok_block)
    check("skill links the dispatch reference", "references/worker-dispatch.md" in skill)
    check("the orchestrator removes the lock when a worker returns or fails; the skill only points there",
          'crew-progress.py lock remove "$WORK_DIR"' in reference and "returns or fails" in reference
          and "lock remove" not in skill and "lock write" not in skill)
    check("reference gives the branch commands for the in-place default",
          'git -C "$WORK_DIR" switch' in reference and "origin/" in reference)
    check("reference describes the lock file", ".crew-worker.lock" in reference and "info/exclude" in reference)
    check("reference says the lock now protects the main tree", "main tree" in reference and "CREW_WORKER_TASK" in reference)
    check("reference writes the lock at dispatch", "lock write" in reference)
    builder = BUILDER.read_text(encoding="utf-8")
    check("builder removes the lock on exit", "lock remove" in builder and ".crew-worker.lock" in builder)
    check("builder exports CREW_WORKER_TASK so the guard exempts it", "export CREW_WORKER_TASK" in builder and "CREW_WORKER_TASK=" in builder)
    worktree_choice()
    lock_round_trip()
    for failure in FAILURES:
        print(f"failed: {failure}", file=sys.stderr)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
