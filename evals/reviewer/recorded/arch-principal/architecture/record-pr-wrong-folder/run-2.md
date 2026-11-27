Assessment: request-changes — `branch_tree` looks for the branch's worktree from the wrong directory and ignores the recorded `worktree`, so the DONE gate can still run against the wrong HEAD.

Read beyond the package: `.agent/tools/lib/git.py`

Approach: redirect — Use the task's recorded `.task-id` `worktree` (or run `worktrees()` from it) as the source of truth. Keep the branch lookup only as a fallback.
Alternatives considered:
- Use the recorded `worktree` from `.task-id` — it is the authoritative record of where the task was implemented, and it needs no git call or branch-name match. It wins. Its weakness is staleness if the worktree was moved or removed, so check that the directory exists and fall back to the branch lookup.
- Have `mark_done` take a `root` or `cwd` argument instead of the caller using `os.chdir` — this removes the process-global state change. It is the cleaner design, and it is better than the chdir if `mark_done` can be changed.
- Do nothing and require the user to run `mark-done` manually — the failure message already prints that command, but it makes the hook pointless.

1. [attention · 4] **`.agent/tools/task/task_record_pr.py:13`** — the worktree lookup runs from the session's cwd, not from the task's repository
```
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` runs `git worktree list` in the current directory. Here that is the payload `cwd`, or whatever `record` left it as. If the session runs in an unrelated folder, or in another repository, the call either raises `GitError` or lists the wrong repository's worktrees. Either way `branch_tree` returns `None`. `close` then runs `mark_done` in that same wrong directory, so the DONE gate checks the wrong HEAD or reports a bogus failure. The task's recorded `worktree` is never consulted, even though the change description names it as the source of truth.
Fix: Try the task's recorded `worktree` first, if that directory exists. Otherwise call `worktrees(root=<that path or the repo root>)`. Fall back to the current directory last.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:15`** — a `GitError` is swallowed and the gate then runs in the wrong place
```
except GitError:
    return None
```
When the lookup fails, `close` quietly runs `mark_done` in the session cwd. If that cwd is another repository's HEAD, the gate can report "review covers HEAD" for the wrong commit, or fail with a confusing message. Nothing tells the user that the worktree was not found.
Fix: When the lookup returns `None`, add a `record-pr:` line saying the worktree was not found. Prefer to skip the gate and print the manual `MARK_DONE` command rather than run it in an unknown directory.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:24`** — `os.chdir` and stdout redirection are process-global
```
os.chdir(tree) ... contextlib.redirect_stdout(out)
```
`record` and `close` each change the directory and restore it. This is safe in a one-shot hook but fragile if the code is ever called from a threaded or long-lived process. It also spreads the "which directory" decision across two functions.
Fix: Pass an explicit `root` to `mark_done` and to the git reads.