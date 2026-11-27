Assessment: request-changes — the hook looks for the PR's worktree through the session's cwd, which is the folder the change was meant to stop depending on.

Read beyond the package: `.agent/tools/lib/git.py`, grep of `.agent/tools` for `worktree`

Approach: redirect — Use the worktree the task already recorded, not a lookup keyed on branch name from the session's cwd.
Alternatives considered:
- Use the `worktree` field from the task's `.task-id`, with a check that its remote matches the task's repository URL — this wins. The task already owns that fact, and the lookup no longer depends on where the session runs.
- Call `worktrees(root=<task repo>)`, with the root taken from the task's recorded path — a fallback when `.task-id` has no `worktree`. It is still better than the current code, because it scopes the lookup to the right repository.
- Do nothing and run the gate in the payload cwd — this leaves the case unmet where the session runs in another folder or repository. The gate then checks the wrong HEAD, which is the problem the change is meant to fix.
- Pass the worktree to `mark_done` as a parameter — the cleanest design, since it removes the process-global `chdir`. It needs a signature change, so it is a larger edit.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:13`** (h1) — worktree lookup runs in the session cwd, not the task's repository
```
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` defaults to `root=None`, so it lists the worktrees of whatever repository `record()` left as cwd (the payload `cwd`). Say the session runs in an unrelated folder, or in a different repo's checkout. Either `git worktree list` fails, which the `GitError` handler turns into `None`. Or it lists the wrong repo, and a branch with the same name (such as `main` or `feature`) matches the wrong tree. In both cases `close()` runs `mark_done` in the wrong directory and the gate checks the wrong HEAD. It can report "review covers HEAD" for the wrong commit, or fail a correct PR.
Fix: take the worktree from the task's `.task-id` `worktree` field. Call `worktrees(root=...)` only after confirming the repository's remote URL matches the task's recorded URL.

2. [attention · 4] **`.agent/tools/task/task_record_pr.py:14`** (h1) — the fallback to cwd is silent
```
except GitError:
    return None
```
When the lookup fails, `close()` skips the `chdir` and runs the DONE gate in the wrong directory. The only effect is that the output is wrong or confusing. The worktree can't be found for another reason too: it was removed after the PR was opened. The user can't tell which of these happened.
Fix: when no worktree is found, return a line such as `record-pr: no worktree for <branch>; run mark-done from it`. Don't run the gate against an unrelated HEAD.

3. [attention · 3] **`.agent/tools/task/task_record_pr.py:24`** (h1) — the gate's repository is chosen through a process-wide `os.chdir`
```
os.chdir(tree)
...
code = mark_done(r.task, url, False)
```
`mark_done` finds its repository through the implicit cwd, and `record()` already changes directory once before `close()` changes it again. A third caller that is added later, or a failure between the two changes, makes the gate use whichever directory happens to be current. A redirected stdout carries the gate's messages, so the wrong directory can also pass unnoticed.
Fix: give `mark_done` and `worktrees` an explicit `root` or `cwd` argument and drop the `chdir` calls.