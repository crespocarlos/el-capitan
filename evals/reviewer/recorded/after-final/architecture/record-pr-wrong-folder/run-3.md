Assessment: request-changes — the worktree lookup depends on the session's cwd, which is the folder the change was meant to stop depending on, and it ignores the `.task-id` `worktree` field that the task already records.

Read beyond the package: `.agent/tools/lib/git.py`, plus a grep for `worktree` across the tree.

1. [attention · 4] **`.agent/tools/task/task_record_pr.py:14`** — `branch_tree` lists worktrees from the session cwd, not from the task's repository
```
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` is called with no `root`, so it runs `git worktree list` in whatever directory the process is in. In `close`, that directory is the payload `cwd` set by `record`. If the session runs outside the PR's repository, for example in an unrelated checkout, `git` raises `GitError` and `branch_tree` returns `None`. If the cwd is a different repository, it finds no match and also returns `None`. In both cases `mark_done` then runs in the wrong folder and checks the review against the wrong HEAD. That is the bug this change was written to fix. The task already stores its repository (remote URL) and the `worktree` it was implemented in, so the code has a more reliable source than the cwd and doesn't use it.
Fix: resolve the tree from the task record first. Use the recorded `.task-id` `worktree` if it exists on disk and has `branch` checked out, for example via `worktrees(root=recorded)`. Fall back to the cwd search only after that, and check the remote URL matches the task's repository.

2. [attention · 4] **`.agent/tools/task/task_record_pr.py:25`** — the DONE gate runs against the wrong repository without any warning when no worktree is found
```
if tree is not None:
    os.chdir(tree)
with contextlib.redirect_stdout(out), ...
    code = mark_done(r.task, url, False)
```
When `tree is None`, the code runs `mark_done` in the payload cwd and says nothing. Two cases follow. A review for the right HEAD may be reported as stale or missing, so the task stays open with a misleading message. Worse, if the cwd is another repository whose HEAD happens to be covered by a review, the task could be marked DONE against a HEAD that is not the PR's branch. The two outcomes, no worktree found and worktree found, are not distinguishable in the output.
Fix: if `branch_tree` returns `None`, don't run the gate. Return a line such as `record-pr: no worktree has <branch> checked out; run mark-done from it`. Alternatively, pass the repository root explicitly to the gate instead of relying on the process cwd.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:21`** — process-global `os.chdir` is used as a parameter
`close` and `record` both `chdir` and restore the old directory in `finally`. This hides a dependency on the cwd that `mark_done` has. It is also not safe if the hook is ever called from threads, or in-process from a test runner. The cost is that every caller has to know about this ambient state. Passing `root` to `mark_done` would remove it.