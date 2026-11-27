Assessment: request-changes — the hook looks up the worktree from the session's cwd. It ignores the `worktree` the task recorded, so the DONE gate can still run in the wrong repository or fail silently.

Read beyond the package: `.agent/tools/lib/git.py`, plus a grep of `.agent/tools` for `worktree`.

1. [attention · 4] **`.agent/tools/task/task_record_pr.py:14`** — worktree lookup uses the session cwd, not the task's recorded `worktree`
```
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` runs `git worktree list` in the process cwd. `record()` has already chdir'd to the payload `cwd`, which is the folder the session runs in. The task already stores its repository's remote URL and the worktree it was implemented in (`.task-id` `worktree`), and nothing here uses either.

Scenario: the session runs in an unrelated repo, or in a folder that isn't a git repo. `worktrees()` then lists the wrong repo's worktrees, or raises `GitError`. `branch_tree` returns `None`, and `close` runs `mark_done` in the unrelated cwd. The gate then checks the review against the wrong HEAD, or fails, and the task stays in its old state. This is the case the change was written to fix.

The lookup should be anchored on the task's own repo. Take the recorded `worktree` first, and call `worktrees(root=recorded)`. Fall back to the cwd lookup only when no worktree is recorded.

Fix: pass the task's recorded worktree as the root, e.g. `worktrees(root=recorded_worktree)`. Prefer the recorded path itself when it still exists and has `branch` checked out.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:24`** — a failed worktree lookup or a missing branch is silent, and the gate runs in the wrong place
```
tree = branch_tree(branch)
try:
    if tree is not None:
        os.chdir(tree)
```
`branch_tree` returns `None` for two different reasons: no worktree has the branch, or `GitError`. In both cases `mark_done` runs in whatever directory the session is in. It then checks the wrong HEAD and reports "review does not cover HEAD", or passes against an unrelated repo. Nothing tells the user the fallback happened.

Fix: when `tree` is `None`, don't run the gate. Emit a `record-pr:` line saying the worktree for `branch` was not found, and print the `MARK_DONE` command to run by hand.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:22`** — the hook changes the process cwd in two nested places
```
out, saved = io.StringIO(), os.getcwd()
```
`os.chdir` is process-global state, and `record` and `close` each save and restore it separately. The gate could instead be given an explicit `cwd` or `root` argument, which would remove the cwd-dependent behaviour from `mark_done`. That would also have prevented the finding 1 class of bug.