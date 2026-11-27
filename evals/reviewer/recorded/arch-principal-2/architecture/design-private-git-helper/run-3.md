Assessment: request-changes — the check re-implements the shared git module, and that drops its guarantee that empty output is never read as an answer. As a result, failures read as matches or as wrong reports.

Read beyond the package: `.agent/tools/lib/git.py`, plus a grep for other `doctor`, `slug` and `TASKS` uses (none found outside this module).

Approach: redirect — build the check on `lib/git.py` (`current_branch`, `remote_url`, `slug_from_url`, `GitError`) instead of a private `_git` and `_slug`.
Alternatives considered:
- Use the shared module, with `GitError` mapped to a WARN row per task — this wins. It is the one door to git for the Python tools and already has timeouts, a detached-HEAD guard and `None` for a missing remote.
- Keep the private `_git` and `_slug` (the chosen design) — this loses. It starts a second way of calling git and a second copy of the slug rule.
- Don't build it and rely on `git worktree list` — this leaves part of the need unmet. It cannot check the task's branch or its `repo_remote_url`, and it does not read the `.task-id` records.

I found no other consumers. Only the new module itself references `TASKS`, and the diff does not show how `crew doctor` calls it.

1. [blocking · 5] **`.agent/tools/maintenance/doctor_worktrees.py:14`** — the private `_git` swallows failures and returns empty output, which the shared module forbids
```
result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
return result.stdout.strip()
```
Take a worktree directory that is not a git repository, or a worktree whose git call times out or fails. `_git` returns `""` and the check goes on. `branch` becomes `""` and the row says "is on , not X". `origin` becomes `""`. If the task's `repo_remote_url` is also empty or missing, `_slug("") == _slug("")` and the check passes silently. A broken worktree is then reported as healthy or with a wrong reason. There is also no timeout, so a hung git call stalls `crew doctor`.
Fix: delete `_git` and call `lib.git.current_branch` and `remote_url`. Catch `GitError` and append a WARN row such as "cannot read git state: …".

2. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:17`** — `_slug` duplicates `slug_from_url` (a fact with two owners)
```
def _slug(url: str) -> str:
    tail = url.rstrip("/").removesuffix(".git")
```
Both functions derive `owner/name` from a remote URL. They already differ. The shared one strips whitespace and returns `None` for a URL with no slash. `_slug("")` returns `""`, so a missing origin and a missing `repo_remote_url` compare as equal and the task passes. When the shared rule changes, for example to support another host form, doctor will disagree with the tools that create the worktrees.
Fix: use `slug_from_url`. Treat a `None` slug on either side as a WARN ("no usable repository URL recorded"), not as a match.

3. [attention · 3] **`.agent/tools/maintenance/doctor_worktrees.py:24`** — one bad `.task-id` file or a detached HEAD breaks the check
```
meta = json.loads(meta_path.read_text())
...
branch = _git(tree, "rev-parse", "--abbrev-ref", "HEAD")
```
A malformed or unreadable `.task-id` raises out of `check_worktrees`, so doctor loses the rows for every other task. A detached HEAD gives `"HEAD"`, which is reported as a branch name. `current_branch` already raises `GitError` for that case.
Fix: wrap the per-task body in a handler for `json.JSONDecodeError`, `OSError` and `GitError`. Emit a WARN row for that task and continue.

4. [nit · 3] **`.agent/tools/maintenance/doctor_worktrees.py:8`** — `TASKS` is hard-coded to `~/.agent/tasks`
If another doctor check or the task tooling already owns this location, a second constant will drift from it. I found no other definition in the working directory, so I could not confirm there is one. The cost is a second place to edit if the task directory moves.
Fix: import the location from wherever tasks are created, if such a constant exists.