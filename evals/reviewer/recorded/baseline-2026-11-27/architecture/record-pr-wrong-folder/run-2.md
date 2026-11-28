Assessment: request-changes — `branch_tree` looks the worktree up from the session's folder and a branch name, not from the task's recorded repo and worktree. The DONE gate can run against the wrong repo or HEAD.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:13`** (h1) — worktree lookup runs in the session's cwd and matches on branch name only
```python
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` with no `root` lists the worktrees of whatever repository the payload `cwd` is in. `record()` has just done `os.chdir(cwd)`, and that folder is not guaranteed to be the PR's repo. The task records its repo's remote URL and `.task-id` `worktree`, and this code uses neither. If the session runs in another repo, one of two things happens. Either no branch matches, or a same-named branch such as `fix-ci` in the other repo matches. The gate then checks the review against the wrong HEAD, and it can mark the task DONE or refuse to for the wrong reason.
Fix: resolve the tree from the task. Prefer the `.task-id` `worktree` path if it exists and is a worktree of the repo whose remote matches the task's URL. Otherwise call `worktrees(root=<task worktree or repo>)`. Never match on the branch name alone.

2. [attention · 4] **`.agent/tools/task/task_record_pr.py:24`** — silent fallback to cwd when no worktree is found
```python
if tree is not None:
    os.chdir(tree)
with ...:
    code = mark_done(r.task, url, False)
```
When `branch_tree` returns `None`, or swallows a `GitError` at line 14, `mark_done` still runs in the session folder. The gate's "latest review covers HEAD" check then compares against an unrelated checkout. This is the exact failure the change was meant to prevent, and it gives no warning. A wrong-repo pass could mark the task DONE. A wrong-repo fail leaves it stuck with a misleading message.
Fix: when no tree is resolved, skip the gate. Emit `record-pr: cannot find the worktree for <branch>; run: MARK_DONE…` and leave the task's state unchanged.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:21`** — gate depends on process-global `os.chdir`
`mark_done` takes its HEAD from the process cwd, so the contract is implicit and tied to global state. `worktrees()` already accepts a `root`. Giving `mark_done` a `repo` or `root` parameter would remove the chdir juggling in both `close` and `record`, and the restore-on-exception paths along with it. This is optional.