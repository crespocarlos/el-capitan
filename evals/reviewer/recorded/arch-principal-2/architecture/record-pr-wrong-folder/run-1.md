Assessment: request-changes — the worktree is found from the session's cwd and the branch name, so it can be the wrong repo or none. The task already records the worktree it was implemented in, and that is the owner this change should use.

Read beyond the package: `.agent/tools/lib/git.py`, plus a grep of `.agent` for `worktree`.

Approach: redirect — resolve the gate's directory from the task's recorded `worktree` (`.task-id`) and repository URL, not by searching the session cwd's worktree list for a branch name.
Alternatives considered:
- Use the task's recorded `worktree` (and remote URL) — this wins. The task already stores it, so the lookup stops depending on where the session ran. The recorded worktree can be stale, so check that it exists and that its HEAD is on the PR branch. Otherwise fall back to the branch search.
- Make `mark_done` take a `repo`/`cwd` argument instead of using `os.chdir` — also better. It removes process-wide state changes from a hook and gives the DONE gate one explicit directory.
- Don't build the worktree lookup; leave the gate running in the session cwd — this is the status quo. It fails when the session runs in a different folder, which is the problem this change is meant to fix.

1. [attention · 4] **`.agent/tools/task/task_record_pr.py:13`** — the worktree is looked up in the session cwd's repository, not the task's
```python
return next((path for path, name in worktrees() if name == branch), None)
```
`worktrees()` runs `git worktree list` in the current directory. `record()` has already changed into `payload["cwd"]`, and tasks are keyed by remote URL, so that folder may belong to a different repository or to no repository. Take a session in an unrelated repo that has a branch with the same name, such as `main` or `fix-x`. The lookup returns that repo's worktree and the DONE gate checks the review against the wrong HEAD. If the folder is not a repo, `GitError` makes `branch_tree` return None, and the gate then runs in the wrong place without any warning. The lookup also never compares the repository URL.
Fix: In `close`, use the task's recorded `worktree` when that directory exists and its checked-out branch matches. Only then fall back to `worktrees(root=...)`. When no repository can be determined, report that rather than gating in the wrong folder.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:26`** — a silent fallback to the session cwd, with `chdir` as shared state
```python
if tree is not None:
    os.chdir(tree)
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
    code = mark_done(r.task, url, False)
```
When `tree` is None, `mark_done` still runs in the session cwd. That is the same wrong-folder condition this change was written to fix, and nothing is printed about it. The gate can then report that the review does not cover HEAD, or it can pass against an unrelated HEAD. `os.chdir` and the redirected stdout/stderr are process-global, so the same pattern would be unsafe if the hook ever ran concurrently.
Fix: When no worktree is resolved, return a line saying so and skip the gate, leaving the task not done. Better still, pass the directory into `mark_done`.

Handoff to adversarial: `.agent/tools/task/task_record_pr.py:21` — `mark_done` runs once the PR is appended, so a failure after `append_pr` is not rolled back.