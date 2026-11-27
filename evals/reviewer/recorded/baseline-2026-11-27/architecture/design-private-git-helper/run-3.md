Assessment: request-changes — the new module bypasses the shared git module (`lib/git.py`) with its own `_git` and `_slug`, and its failure handling produces wrong doctor output.

1. [blocking · 5] **`.agent/tools/maintenance/doctor_worktrees.py:12`** — `_git` bypasses the shared git module and swallows failures
```python
result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
return result.stdout.strip()
```
`lib/git.py` is documented as "the one door to git", and every helper there raises `GitError` when git cannot answer, because "empty output is never read as an answer". This helper uses `check=False` and has no timeout. If `tree` is a directory but not a repository, `rev-parse` fails and returns `""`. The row then reads "is on , not X", which is misleading. A missing origin is also reported as a remote mismatch rather than as "no origin". A hung git call blocks the whole `crew doctor` run.
Fix: delete `_git`. Use `git.current_branch(tree)` and `git.remote_url(tree)`. Catch `GitError` per task and emit a WARN row such as "not a usable git repository".

2. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:19`** — `_slug` duplicates `slug_from_url` and loses its None handling
```python
tail = url.rstrip("/").removesuffix(".git")
return "/".join(tail.replace(":", "/").split("/")[-2:])
```
`git.slug_from_url` already does this, and it returns None for empty or short input. Here, if both the origin and `repo_remote_url` are empty, both slugs are `""`. They compare equal, so a worktree with no origin and a task with no recorded repository pass silently. Two parallel parsers will also drift apart.
Fix: use `git.slug_from_url`. Treat a None result on either side as its own WARN ("unknown repository") instead of comparing it for equality.

3. [attention · 3] **`.agent/tools/maintenance/doctor_worktrees.py:34`** — a detached HEAD is reported as the branch name "HEAD"
```python
branch = _git(tree, "rev-parse", "--abbrev-ref", "HEAD")
if branch != meta.get("branch"):
```
A detached HEAD returns `HEAD`, so the row reads "is on HEAD". `git.current_branch` raises `GitError` for this case, and the check should map that to an explicit "detached HEAD" row.
Fix: use `current_branch` and handle `GitError` with a distinct message.

4. [nit · 3] **`.agent/tools/maintenance/doctor_worktrees.py:27`** — one malformed `.task-id` aborts the whole check
`json.loads(meta_path.read_text())` is not guarded. A single corrupt file raises out of `check_worktrees`, so no task gets checked. A doctor check should report the bad file as a WARN row and continue.