Assessment: request-changes — the hook picks the worktree by branch name in whatever repo the session is in, and ignores the task's recorded `worktree` and remote URL. If the session is in another repo, the DONE gate checks the wrong HEAD.

Read beyond the package: `.agent/tools/lib/git.py`. A grep for `worktrees`, `mark_done` and `GitError` found only the `worktrees` definition. The other two are not defined anywhere in the files I have.

1. [attention · 4] **`.agent/tools/task/task_record_pr.py:14`** (diff, `branch_tree`) — the worktree is derived from the session's repo by branch name, though the task already records it
```
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` runs `git worktree list` in the current directory. Here that is the payload `cwd`, because `record` has already done `os.chdir(cwd)`. Suppose a session in repo A runs `gh pr create` for a task from repo B, or in a non-worktree folder. Branch names like `feature/x` can also repeat across repos. Then there is no match, or the wrong match. `branch_tree` returns `None`, and `close` runs `mark_done` in the unrelated cwd. The gate then checks the review against that repo's HEAD, which either falsely blocks DONE or falsely passes it. The task's `.task-id` `worktree` and its remote URL are the authoritative facts. This design keeps a second copy of the worktree fact, derived by a heuristic.
Fix: resolve the tree from the task's recorded `worktree`, after checking that it exists and that its remote matches the task's repo URL. Use `worktrees(root=recorded)` for the branch lookup only as a fallback. When nothing resolves, do not run the gate in the wrong repo. Report "cannot locate worktree" and print the manual `MARK_DONE` command.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:14`** (diff, `branch_tree`) — `except GitError` does not cover what `worktrees()` raises
```
except GitError:
    return None
```
`worktrees()` uses `subprocess.run(..., check=True, timeout=10)`. It raises `CalledProcessError`, `TimeoutExpired` or `FileNotFoundError`, none of which I can see mapped to `GitError`. `GitError` is not defined in `lib/git.py`, and I could not confirm where it comes from. If it is not a wrapper for these, a hook fired from a non-git folder raises out of `close`. The PR is already appended, but the gate and the output never run. This is a possible pre-existing contract gap, in the `lib/git.py` interface.
Fix: have `worktrees` wrap these exceptions in `GitError`, or catch `(subprocess.SubprocessError, OSError)` here.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:24`** (diff, `close`) — the gate depends on the process-global cwd
```
os.chdir(tree)
...
code = mark_done(r.task, url, False)
```
`mark_done` reads HEAD from the implicit cwd. That coupling needs two nested chdir/restore pairs in `record` and `close`. Passing the repo root to `mark_done` would remove the global state and make fix 1 testable.