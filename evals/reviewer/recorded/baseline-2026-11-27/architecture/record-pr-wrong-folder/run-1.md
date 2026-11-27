Assessment: request-changes — the hook picks the worktree by branch name from whatever repo the session is in, and ignores the task's recorded remote and worktree, so the DONE gate can check the wrong repo's HEAD.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:13`** — worktree is found by branch name in the session's repo, not the task's repo
```python
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` takes `root=None`, so it lists the worktrees of the payload `cwd`, which `record()` has just `chdir`'d into. The change description says the hook fires in any folder, so that repo may not be the PR's repo. Branch names such as `main` or `fix-x` repeat across repos. The match can then select a different repository's worktree, and `mark_done` checks the review against that HEAD. The task already records the authoritative data, the repo remote URL and the `.task-id` `worktree`. `close()` never reads either one. Fix: take the worktree from the task's recorded `worktree`. If that is missing, call `worktrees(root=<task's repo>)` and confirm the remote URL matches the task's remote before accepting a branch match.

2. [attention · 4] **`.agent/tools/task/task_record_pr.py:28`** — falls back silently to the wrong cwd when no worktree is found
```python
if tree is not None:
    os.chdir(tree)
with ... : code = mark_done(r.task, url, False)
```
When `tree` is `None`, `mark_done` runs in the payload `cwd`. That is the folder the change was meant to stop depending on. It gives a spurious pass or fail against an unrelated HEAD and prints no warning. Fix: when no worktree resolves, skip the gate and emit a line such as `record-pr: cannot locate worktree for <branch>; run mark-done from it`. Do not run the gate in the wrong folder.

3. [attention · 3] **`.agent/tools/task/task_record_pr.py:14`** — the `except GitError` does not match what `worktrees()` raises
```python
except GitError:
    return None
```
`worktrees()` in `lib/git.py:10` uses `subprocess.run(..., check=True, timeout=10)`. That raises `CalledProcessError`, `TimeoutExpired` or `FileNotFoundError`, and nothing in `git.py` wraps them in `GitError`. If `GitError` is not raised, a non-repo cwd (for example a session started outside any repo) crashes the hook instead of falling back. The excerpt doesn't show where `GitError` is defined or imported, so I couldn't confirm this. Fix: catch `(subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError)`, or have `worktrees` raise `GitError`.

4. [nit · 3] **`.agent/tools/task/task_record_pr.py:21`** — process-global `chdir` is nested across `record` and `close`
`record` and `close` each save and restore the cwd with `os.chdir`. That is safe in a single-threaded hook. It does couple every callee to ambient state, which is how the wrong-folder bug arose. Passing `root`/`cwd` explicitly to `pull`, `worktrees` and `mark_done` removes the cost of future callers inheriting a surprising directory.