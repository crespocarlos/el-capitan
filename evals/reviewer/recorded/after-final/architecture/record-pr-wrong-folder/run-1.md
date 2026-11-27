Assessment: request-changes — the worktree is found by listing worktrees of the session's cwd repo, not from the task's recorded `worktree`, so it fails when the session runs in another repo.

Read beyond the package: .agent/tools/lib/git.py

1. [attention · 4] **`.agent/tools/task/task_record_pr.py:14`** — branch_tree looks in the wrong repository and ignores the task's recorded worktree
```
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` runs `git worktree list` in the process cwd. In `record`, that cwd is the payload `cwd`, which can be any folder the session was started in. If the session runs in a different repo, or in a non-git folder, the call returns that repo's worktrees or raises `GitError`. Either way the result is `None`, and `close` runs `mark_done` from the wrong directory. The DONE gate then checks the review against the wrong HEAD, which is the bug this change set out to fix. The task already records its repo's remote URL and `.task-id` `worktree`, so the right location is known, but this code doesn't use it. Matching on branch name alone also picks the wrong tree when two repos use the same branch name.
Fix: take the directory from the task's recorded `worktree`, and check that its remote matches the task's remote URL. Call `worktrees(root=that path)` only as a fallback. Don't rely on the payload cwd.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:24`** — `chdir` into a worktree and a silent fallback to the session folder
```
if tree is not None:
    os.chdir(tree)
...
code = mark_done(r.task, url, False)
```
When no worktree is found, the gate silently runs against the session cwd. It can then pass or fail on an unrelated HEAD, with no message saying which directory was used. Process-global `os.chdir` is also shared state that every nested call depends on. Passing a `root` to `mark_done` would avoid that.
Fix: if no worktree resolves, don't run the gate. Report "cannot locate worktree for <branch>" and keep the task in its current state. Prefer an explicit root parameter on `mark_done` over `chdir`.