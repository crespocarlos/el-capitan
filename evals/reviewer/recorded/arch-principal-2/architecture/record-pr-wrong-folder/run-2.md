Assessment: request-changes — the hook looks for the PR's worktree in whatever repo the session happens to be in, when the task already records the worktree path and repo URL.

Read beyond the package: `.agent/tools/lib/git.py`, and a grep for `GitError`, `mark_done` and `worktree` across the tree.

Approach: redirect — resolve the gate's directory from the task's recorded `.task-id` `worktree`, and verify the remote URL, instead of searching the current repo's worktrees by branch name.
Alternatives considered:
- Use the task's recorded `worktree` (and its remote URL) — it wins. It is the authoritative record of where the task was implemented, it works when the session `cwd` is another repo or folder, and it needs no branch-name guess.
- Give `mark_done` a `cwd`/`root` parameter instead of calling `os.chdir` — it wins. It removes process-global state, and `close` and `record` currently nest two chdir/restore pairs.
- Keep the branch lookup as a fallback only — it loses as the primary path. It is only correct when the session `cwd` is already in the PR's repository.
- Do nothing (gate runs in the payload `cwd`) — it loses. That is the bug being fixed: the gate checks the wrong HEAD.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:13`** — the branch lookup searches the session's repo, not the task's repo
```
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` runs with the default cwd, which is the payload `cwd` after `record()` changed into it. If the session runs in a different repo or an unrelated folder, the branch is not found, `tree` is `None`, and the gate runs against that folder's HEAD. If a different repo has a branch with the same name (`main`, `fix-123`), the gate runs in that repo and checks the wrong review. Either way the DONE gate gives a wrong pass or fail. The task already has the correct answer in its `.task-id` `worktree` and its remote URL.
Fix: take the worktree from the task's recorded `worktree`, check that it exists and that its remote matches the task's URL, and use the branch search only as a fallback with the same remote check. If neither gives a tree, report it and do not run the gate.

2. [attention · 4] **`.agent/tools/task/task_record_pr.py:21`** — no worktree found means the gate quietly runs in the wrong place
```
if tree is not None:
    os.chdir(tree)
```
Detached-HEAD worktrees have no `branch` line in `git worktree list --porcelain`. A removed worktree or a branch checked out nowhere also gives `None`. In those cases the gate runs in the session `cwd` and reports pass or fail for an unrelated HEAD. The user sees only `record-pr: ...` lines with no sign that the check was against the wrong directory.
Fix: when `tree is None`, add a line saying the worktree was not found and do not mark the task DONE, or fail the gate.

3. [attention · 3] **`.agent/tools/task/task_record_pr.py:14`** — `except GitError` does not match what `worktrees()` raises
```
except GitError:
    return None
```
`lib/git.py:10` calls `subprocess.run(..., check=True, timeout=10)`. That raises `CalledProcessError` (cwd is not a repo), `TimeoutExpired`, or `FileNotFoundError` (no git). I found no `GitError` defined or imported in the files I could read, so the name may be undefined, or the wrapper may live elsewhere. If so, a hook fired from a non-git folder raises out of `close()` after `append_pr`. The PR is recorded but the hook crashes, and the `finally` is not reached in `branch_tree`.
Fix: catch `(subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError)` here, or have `worktrees` convert them to `GitError`, and confirm that `GitError` is imported.

4. [nit · 3] **`.agent/tools/task/task_record_pr.py:19`** — `os.chdir` in two nested places
`record()` and `close()` each change the process directory and restore it, and `redirect_stdout` is also process-global. Any later caller that runs these in a thread or in-process test would see the cwd changes. Passing a `cwd`/`root` into `mark_done` and `worktrees(root)` (which already accepts `root`) removes the nesting.