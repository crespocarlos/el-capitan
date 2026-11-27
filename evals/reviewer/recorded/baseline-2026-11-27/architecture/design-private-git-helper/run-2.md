Assessment: request-changes — the check re-implements the shared git module, and its private `_git` swallows failures, so a broken worktree can pass silently.

1. [blocking · 5] **`.agent/tools/maintenance/doctor_worktrees.py:11`** — private `_git` bypasses the shared git door and reads failures as answers
```python
result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
return result.stdout.strip()
```
`lib/git.py` describes itself as "the one door to git" and raises `GitError` when git cannot answer, because "empty output is never read as an answer." This helper uses `check=False` and has no timeout, so every failure becomes `""`. Cases:
- A directory that is not a repository, or a corrupt one, returns `""` for the branch. The row reads "is on , not X", which misdescribes the problem.
- A missing `origin` returns `""`. `_slug("")` becomes `""`, and a task with no `repo_remote_url` also gives `""`. The two compare equal, so a worktree with no origin passes the check against a task with no recorded URL.
- A hung git call blocks `crew doctor`.

Fix: delete `_git`, `subprocess` and the `-C` call. Import `current_branch` and `remote_url` from `lib.git`. Catch `GitError` per task and emit a WARN row such as "cannot read git state: …".

2. [attention · 5] **`.agent/tools/maintenance/doctor_worktrees.py:17`** — duplicate `_slug` that has diverged from `slug_from_url`
```python
def _slug(url: str) -> str:
    tail = url.rstrip("/").removesuffix(".git")
    return "/".join(tail.replace(":", "/").split("/")[-2:])
```
This copies `lib.git.slug_from_url`, minus the `strip()`, the `None` handling and the "fewer than 2 parts" guard. Any later change to remote parsing, such as supporting other hosts, will have to be made twice. A URL without a path, or an empty URL, yields a bogus slug instead of `None`.

Fix: use `slug_from_url`. Treat `None` on either side as "cannot compare" and emit a WARN, not as equal.

3. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:34`** — detached HEAD is reported as a branch name
```python
branch = _git(tree, "rev-parse", "--abbrev-ref", "HEAD")
if branch != meta.get("branch"):
```
A detached worktree gives the literal `HEAD`, and the row says "is on HEAD". `current_branch` raises `GitError` for this case, and the doctor can report it explicitly.

Fix: call `current_branch` and handle `GitError` as in finding 1.

4. [nit · 3] **`.agent/tools/maintenance/doctor_worktrees.py:27`** — one malformed `.task-id` aborts the whole doctor run
```python
meta = json.loads(meta_path.read_text())
```
A single corrupt metadata file raises out of `check_worktrees`, so the other tasks are not checked. A doctor check should report the bad file as a row and continue.

Fix: wrap the read in `try/except (OSError, ValueError)` and append a WARN row for that task.