Assessment: request-changes — the new module bypasses the shared git module, so a git failure is reported as a wrong branch or remote, and `_slug` duplicates `slug_from_url`.

1. [attention · 5] **`.agent/tools/maintenance/doctor_worktrees.py:12`** — `_git` bypasses `lib/git.py` and turns git failures into empty answers
```python
result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
return result.stdout.strip()
```
`lib/git.py` is "the one door to git for the Python tools". Its helpers raise `GitError` when git cannot answer, and "empty output is never read as an answer". `_git` uses `check=False` and has no timeout. If the directory exists but isn't a repository, or git is missing or fails, it returns `""`. The check then reports "is on , not X" and "has origin (none)", which blames the task for a git failure. A detached HEAD returns `"HEAD"` and is reported as a branch name. A hung git blocks `crew doctor` forever. This also adds a second git wrapper that has to be kept in sync with the first.
Fix: Drop `_git`. Use `git.current_branch(tree)` and `git.remote_url(tree)` from `lib/git.py`. Catch `GitError` per task and emit a distinct WARN such as "git could not read {tree}: …". Treat `None` from `remote_url` as "no origin".

2. [attention · 5] **`.agent/tools/maintenance/doctor_worktrees.py:19`** — `_slug` duplicates `git.slug_from_url`, and its behaviour differs
```python
tail = url.rstrip("/").removesuffix(".git")
return "/".join(tail.replace(":", "/").split("/")[-2:])
```
`lib/git.py` already has `slug_from_url`. It strips whitespace, returns `None` for empty input, and returns `None` when there are fewer than two parts. This copy returns `""` for empty input, and for a one-part URL it returns that part. A task with no `repo_remote_url` and a worktree with no origin therefore both give `""`, and `"" == ""` passes silently. A task with no recorded repository is never flagged, and a worktree with no origin is hidden when the task's URL is missing. The two copies will also drift apart over time.
Fix: Use `git.slug_from_url`. Treat a `None` slug on either side as a distinct WARN, for example "task has no repository recorded" or "no origin".

3. [nit · 3] **`.agent/tools/maintenance/doctor_worktrees.py:30`** — one malformed `.task-id` aborts the whole check
```python
meta = json.loads(meta_path.read_text())
```
A single corrupt task file raises `JSONDecodeError`. That stops doctor from reporting on every other task, and the point of a doctor check is to survive damaged state.
Fix: Catch `(OSError, json.JSONDecodeError)` and append a WARN row for that task, then continue.