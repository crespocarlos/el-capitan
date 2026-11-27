Assessment: request-changes — the new module reimplements the shared git module, and its failure handling breaks that module's contract. A git failure comes out as a false WARN or, in one case, as a false pass.

Read beyond the package: `.agent/tools/lib/git.py`, plus a grep for other users of `slug` and `TASKS`. I found no other consumers, and no registration of `check_worktrees` in `crew doctor` appears in the working directory.

Approach: redirect — Use the shared `lib/git.py` (`current_branch`, `remote_url`, `slug_from_url`, `GitError`) instead of a private `_git` and `_slug`.
Alternatives considered:
- Don't build the check, and rely on existing tooling — this loses. Nothing else in the working directory checks recorded worktrees, so the need is unmet.
- Build the check on `lib/git.py` and catch `GitError` per task, turning each into a WARN row — this wins. It has the same size and the same output, and it keeps one owner for git access and for slug parsing.
- Keep the private helper — this loses. Its behavior diverges from the shared module on exactly the inputs a doctor check sees.

1. [blocking · 5] **`.agent/tools/maintenance/doctor_worktrees.py:12`** — private `_git` bypasses the shared git door and reads failures as answers
```
result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
return result.stdout.strip()
```
`lib/git.py` says empty output is never an answer and that every helper raises `GitError` when git cannot answer. This helper uses `check=False` and has no timeout. Take a worktree directory that is not a repository, for example one left behind after `git worktree prune`. The branch read returns "" and the report says "is on , not X". The origin read also returns "", and the row says "(none)". The message hides the real cause, and a hung git blocks doctor forever. The "no origin" case and the "git failed" case also become indistinguishable.
Fix: Replace `_git` with `git.current_branch(tree)` and `git.remote_url(tree)`. Catch `GitError` per task and emit a WARN row that carries the error text.

2. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:17`** — a second `_slug` duplicates `slug_from_url`, and it fails open on an empty slug
```
def _slug(url: str) -> str:
    ...
    if _slug(origin) != _slug(meta.get("repo_remote_url", "")):
```
A task has no `repo_remote_url` and its worktree has no origin. Both slugs come out as `""`, so they compare equal and the check passes. The shared `slug_from_url` returns None for empty input, which can be tested explicitly. A URL with no slash also yields a bare name here, where the shared version returns None. Two owners for slug parsing will drift apart.
Fix: Use `git.slug_from_url`. Emit a WARN when either slug is None, and compare only when both are present.

3. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:33`** — a detached HEAD, a corrupt `.task-id`, and a missing `branch` field are all handled wrongly
```
branch = _git(tree, "rev-parse", "--abbrev-ref", "HEAD")
if branch != meta.get("branch"):
```
A detached HEAD yields "HEAD", so the row reads "is on HEAD". `current_branch` raises on a detached HEAD, which allows a clearer message. `json.loads(meta_path.read_text())` on one malformed `.task-id` raises out of the loop, so one bad task aborts the whole doctor run instead of producing a row for that task.
Fix: Wrap the per-task body in `try/except (GitError, OSError, ValueError)` and emit a WARN row naming the task.

4. [nit · 3] **`.agent/tools/maintenance/doctor_worktrees.py:8`** — `TASKS` is defined here with its own `Path.home()` constant
Any other module that locates the tasks directory can disagree with this one about where it is. I found no other definition in the working directory, so this is only a cost. If doctor already has a tasks-root constant, this value should come from it.
Fix: Reuse the existing constant if there is one. Otherwise leave it as is.