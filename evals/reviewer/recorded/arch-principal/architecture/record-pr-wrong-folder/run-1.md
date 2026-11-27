Assessment: request-changes — the worktree is found by branch name from whatever folder the session is in, so the DONE gate can still run against the wrong repo's HEAD. The task's recorded `worktree` and remote URL are ignored.

Read beyond the package: `.agent/tools/lib/git.py`

Approach: redirect — resolve the gate's directory from the task's own recorded `worktree`, checked against its remote URL, and don't search by branch name in the session's cwd.
Alternatives considered:
- Use the task's `.task-id` `worktree` (the chosen approach ignores it) — wins. It is the owned fact for where the task was implemented, and it needs no git listing or name matching. If the path is gone or its remote doesn't match, fall back to a branch search that runs inside that repo.
- Make `mark_done` take an explicit repo path or HEAD instead of calling `chdir` — wins long-term. The gate no longer depends on process-global cwd, and the nested `chdir` and `finally` blocks in `record` and `close` go away.
- Don't build it and tell the user to run `mark-done` from the worktree — loses. It is the manual step the hook exists to remove, but it is the correct fallback when the worktree can't be resolved.

Price of next changes:
- **Cwd-bound code:** another cwd-sensitive step (for example, a review-freshness check) means adding another `chdir` wrapper.
- **Branch collisions:** repos that reuse branch names such as `main` or `fix/x` make the lookup more ambiguous.
- **Passing the repo path explicitly:** this fixes both cases.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:13`** — the worktree is looked up by branch name in the session's cwd, not the task's repo
```
return next((path for path, name in worktrees() if name == branch), None)
```
`record` has already run `os.chdir(payload["cwd"])`, so `worktrees()` lists the worktrees of whichever repo the session is in. Take a task for repo A whose PR is created from a Claude session in repo B, or in an unrelated folder. Repo B may have no such branch, or may have a different branch with the same name. Either way the lookup returns `None` or repo B's worktree. In both cases the DONE gate checks the review against the wrong HEAD, so it can pass a stale review or block a good one. The task's recorded `worktree` and remote URL, which exist for exactly this, are never read.
Fix: have `close` take the task's `.task-id` `worktree` as the gate's directory. Confirm that its `origin` URL matches the task's recorded remote, then call `worktrees(root=that_path)` only as a fallback.

2. [attention · 4] **`.agent/tools/task/task_record_pr.py:26`** — when no worktree is found, the gate silently runs in the session's cwd
```
if tree is not None:
    os.chdir(tree)
with ... mark_done(r.task, url, False)
```
A `GitError`, a detached HEAD, or a removed worktree makes `branch_tree` return `None`. The gate then runs in the hook's cwd and reports on a HEAD that has nothing to do with the PR, with no hint that the lookup failed. The person sees a misleading "review is stale" or a false pass.
Fix: when no worktree resolves, skip `mark_done`. Print `record-pr: cannot find the worktree for <branch>; run <MARK_DONE command> from it`, and leave the task's state as it is.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:41`** — two nested process-global `chdir` wrappers make the gate depend on cwd
The gate, `record` and `close` each save, change and restore the process cwd, and `close` runs inside `record`'s changed directory. That nesting is why bug 1 exists. Passing a `root` or `repo` argument to `pull` and `mark_done` would remove it. Fix: pass the directory explicitly instead of calling `chdir`.