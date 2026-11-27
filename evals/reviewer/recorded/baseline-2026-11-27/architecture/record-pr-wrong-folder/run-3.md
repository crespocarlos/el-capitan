Assessment: request-changes — `branch_tree` looks for the worktree in whatever repo the hook's `cwd` is in, not in the task's own repo, so the DONE gate can still check the wrong HEAD.

1. [attention · 4] **`.agent/tools/task/task_record_pr.py:11`** — worktree lookup is scoped to the session's cwd repo, not the task's repo
```python
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` defaults to `root=None`, which means the current directory (`git.py:8`). At this point `record()` has already run `os.chdir(payload["cwd"])`. Suppose the Claude session runs in a different repo or folder from the task's repo. `branch_tree` then lists the wrong repo's worktrees. That gives one of two bad results:
- It finds no match and returns `None`. `close` silently falls back to the wrong cwd, so `mark_done` checks the review against the wrong HEAD.
- It matches a same-named branch in the wrong repo, such as `main` or a ticket branch. The gate then runs against an unrelated checkout.

The task already records both the remote URL and the `.task-id` `worktree`, and neither is used here. The PR is matched to the task by URL, and `branch` comes from the PR. Nothing ties the worktree lookup to the task's repo. This code is new, so the defect is not pre-existing.

Fix: resolve the tree from the task's recorded `worktree` (`.task-id`). Use it as `root` for `worktrees(root)`, or use it directly if it still exists. Fall back to matching by branch only inside the repo whose remote URL equals the task's. If no tree can be resolved, do not run the gate against the cwd. Report that the tree is unresolved and print the `MARK_DONE` command.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:21`** — silent fallback to cwd hides the failure
```python
if tree is not None:
    os.chdir(tree)
```
When `tree` is `None`, `mark_done` still runs against whatever directory is current. The output reads as a normal gate result. It can pass a review that covers another repo's HEAD, or fail with a misleading message. `branch_tree` also swallows `GitError`, so the cause is lost.

Fix: when `tree is None`, add a visible line such as `record-pr: no worktree found for <branch>; DONE gate not run` and return the manual `MARK_DONE` hint, instead of calling `mark_done` in the wrong place.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:19`** — process-global `chdir` and stream redirection
`os.chdir` is nested twice, in `record` and in `close`. `redirect_stdout` is also process-global. This is safe in a single-shot hook. It breaks if `record` is ever called from a threaded or long-lived caller. Passing `cwd` into `mark_done` and `worktrees(root)` would remove that hazard. This is only a cost if the function is reused, so it is not worth blocking on.