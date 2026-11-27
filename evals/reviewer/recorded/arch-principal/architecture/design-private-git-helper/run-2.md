Assessment: request-changes — the change rebuilds a git helper and a slug parser that `lib/git.py` already owns, and the rebuilt versions turn git failures into misleading warnings.
Read beyond the package: `.agent/tools/lib/git.py`, plus a grep of `.agent` for other users of these helpers.

Approach: redirect — Build the check on `lib/git.py` (`current_branch`, `remote_url`, `slug_from_url`, `GitError`) and drop the private `_git` and `_slug`.
Alternatives considered:
- Don't build a new module, and add the check to the existing doctor. I found no doctor entry point in the working directory, so I can't tell where it would go. `check_worktrees` also isn't wired to anything I could find. This is a smaller change, but I couldn't verify it.
- Use the shared `lib/git.py`, which is the recommended option. It already has the "empty output is never an answer" contract, timeouts, and a slug parser. It wins because the duplicated code goes away. The check also distinguishes "git failed" from "wrong value".
- Keep the private helpers, which is the chosen approach. It loses because it gives git a second door and the slug rule a second owner.

Likely next changes:
- **Add a fetch or remote reachability check.** This needs timeout and error handling. With the shared module it is one call. With the private `_git` it means rewriting the helper.
- **Handle a detached HEAD or a rename of the slug rule.** Every copy has to change. With the shared module it changes in one place.

1. [attention · 5] **`.agent/tools/maintenance/doctor_worktrees.py:11`** — a second git door that drops the shared error contract
```
def _git(tree: Path, *args: str) -> str:
    result = subprocess.run([... "git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip()
```
`lib/git.py` says it is "the one door to git" and that "empty output is never read as an answer". Here `check=False` and no timeout mean a failing git returns "". Take a worktree directory that is not a repository, or a corrupt one. The branch comes back as "", so doctor reports "is on , not feature-x". The origin comes back as "", so it reports "has origin (none)". Both messages blame the branch or remote when git simply failed. A hung git also blocks doctor forever.
Fix: Delete `_git`. Call `git.current_branch(tree)` and `git.remote_url(tree)`. Catch `GitError` per task and emit a single WARN such as "{name}: cannot read {tree}: {error}".

2. [attention · 5] **`.agent/tools/maintenance/doctor_worktrees.py:17`** — a fact with two owners: the slug rule
```
def _slug(url: str) -> str:
    tail = url.rstrip("/").removesuffix(".git")
    return "/".join(tail.replace(":", "/").split("/")[-2:])
```
`slug_from_url` in `lib/git.py` has the same rule, with a `None` result and a `.strip()`. The copies differ on empty input. Here `_slug("")` returns `""`, so a task with no `repo_remote_url` and a worktree with no origin compare equal. The check passes silently when both are missing. The shared version returns `None` for both, which would hit the same trap if compared with `==`, so the missing case needs an explicit branch.
Fix: Use `git.slug_from_url`. Emit a WARN when the task has no `repo_remote_url`, and a different WARN when the worktree has no origin. Don't compare `None` with `None`.

3. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:30`** — a detached HEAD, a malformed `.task-id` and a slug-less task are not handled
```
meta = json.loads(meta_path.read_text())
...
branch = _git(tree, "rev-parse", "--abbrev-ref", "HEAD")
```
One corrupt `.task-id` raises `JSONDecodeError`, and the whole doctor run crashes, including the check for every other task. A detached HEAD yields the literal "HEAD" and the message "is on HEAD, not X". That is true but unhelpful. `current_branch` raises a clear `GitError` for this case.
Fix: Wrap the per-task body in `try/except (json.JSONDecodeError, OSError, GitError)` and emit a WARN row. Use `current_branch` for the detached case.

4. [nit · 3] **`.agent/tools/maintenance/doctor_worktrees.py:8`** — `TASKS` is a hardcoded `Path.home()` path
`Path.home() / ".agent" / "tasks"` is a second copy of the tasks location. If other tools define it, a change to the location needs edits in several places. I did not find another definition in the working directory, so the cost is unconfirmed.
Fix: Import the tasks directory from wherever the other tools get it, if such a place exists.