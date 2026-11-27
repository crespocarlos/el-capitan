Assessment: request-changes — `branch_tree` calls `worktrees()` from the process cwd, which can be the wrong repository, and it ignores the task's recorded `worktree`.

Read beyond the package: `.agent/tools/lib/git.py`

Approach: redirect — Take the worktree from the task's recorded `.task-id` `worktree`, or pass an explicit `root`. Don't re-derive it from the cwd.
Alternatives considered:
- Use the `worktree` recorded in the task's `.task-id` — it wins. The task already stores the exact path. It needs no git call and can't land in the wrong repository.
- Call `worktrees(root=...)` with a root derived from the task, falling back to the recorded path — it is the second choice. It still matches on branch name, which is ambiguous, but it is scoped to the right repository.
- Don't chdir. Pass the worktree as a `cwd` parameter to `mark_done` — it is cleaner, because it removes the process-global `os.chdir` and the stdout redirection. It needs a signature change in `mark_done`.
- Keep the current approach (cwd-based lookup) — it loses. It works only when the hook's cwd is in the same repository as the task.

1. [attention · 4] **`.agent/tools/task/task_record_pr.py:13`** — branch lookup runs in the hook's cwd, not the task's repository
```
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` is called with no `root`, so it lists the worktrees of whatever repository the process cwd is in. `close` is reached from `record` after `place`, and `record` may have changed into `payload["cwd"]`. `close` runs inside `place`, so that is still the session's folder. Suppose the session runs in an unrelated repository, or in a different clone of the same remote. Then either no worktree is found, or a same-named branch in another clone is found. The DONE gate then checks the review against the wrong HEAD, or against the session folder's HEAD. That is the bug this change was meant to fix. `GitError` is also swallowed, and `worktrees` raises `CalledProcessError` and `TimeoutExpired`, so those are not caught. A non-git cwd therefore raises out of the hook. The code also has two sources for one fact: the recorded `worktree` and the branch name.
Fix: Read the `worktree` from the task's `.task-id`, use it if it is a directory, and fall back to `worktrees(root=<that path>)`. Catch `subprocess.SubprocessError` and `OSError` as well.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:25`** — process-global `os.chdir` plus a stdout redirect to steer the gate
```
os.chdir(tree)
...
code = mark_done(r.task, url, False)
```
A global cwd change inside the hook makes every relative path in `mark_done` depend on it, and the nested `record` chdir stacks on top. If the recorded task directory is relative, or `tasks_dir` is relative, it resolves against the worktree and not the session folder. The failure is a gate that reads the wrong task, or none. A relative path such as `~/.agent/tasks` is fine once expanded, but this is fragile.
Fix: Give `mark_done` an explicit `repo`/`cwd` argument that it passes to its git calls. Drop the `chdir` in `close`.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:12`** — `GitError` is not defined or imported in the excerpt, and `worktrees` does not raise it
```
except GitError:
```
The excerpt does not show where `GitError` comes from. `lib/git.py` has no such class, so the handler may never match the real exceptions. The cost is a crash in the hook instead of the fallback to "no worktree".
Fix: Catch `(subprocess.SubprocessError, OSError)`, or have `worktrees` wrap them in `GitError`.