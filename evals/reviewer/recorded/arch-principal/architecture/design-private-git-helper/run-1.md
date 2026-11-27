Assessment: request-changes — the check is worth building, but it bypasses the shared git module that already does this and so loses that module's no-empty-answer guarantee.

Read beyond the package: `.agent/tools/lib/git.py` (already in the working directory); a grep for other doctor modules and consumers found none.

Approach: redirect — Build the check on `lib/git.py` (`current_branch`, `remote_url`, `slug_from_url`, `GitError`). Don't add a private `_git` and `_slug`.

Alternatives considered:
- Use the shared `lib/git.py` helpers and catch `GitError` per task to emit a WARN row. This wins. It removes about 15 lines, and the module's rule that empty output is never an answer is already enforced there.
- Don't build it and rely on git's own `git worktree list` / `git worktree prune`. This loses. It does not know the task's branch or `repo_remote_url`, so it cannot detect a worktree on the wrong repository or branch.
- Keep the private helper as written. This loses. It is a second way of calling git, and it already disagrees with the shared helper on failures.

Next changes:
- **Detached HEAD, or a new remote host or URL form:** the change is one edit in `lib/git.py` if the check reuses it. Under this design the private copy must be edited as well and will drift.
- **A timeout for slow or networked filesystems:** the shared `run_git` already has one. The private `_git` has none, so `crew doctor` can hang on a stuck worktree.

1. [attention · 5] **`.agent/tools/maintenance/doctor_worktrees.py:12`** — `_git` swallows git failures and turns them into empty strings
```
result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
return result.stdout.strip()
```
A directory that exists but is not a git repository (a stale or emptied worktree) makes `rev-parse` fail with empty stdout. The row then reads "is on , not feature-x", which hides the real cause. If the task's `repo_remote_url` is also missing, `_slug("")` equals `_slug("")`, so the origin check passes for a tree with no origin. `lib/git.py` states that "empty output is never read as an answer", and this helper breaks that rule. It also has no timeout.
Fix: delete `_git`. Call `git.current_branch(tree)` and `git.remote_url(tree)` inside `try/except GitError`, and emit a WARN row such as "not a usable git worktree: {error}".

2. [attention · 5] **`.agent/tools/maintenance/doctor_worktrees.py:17`** — `_slug` duplicates `slug_from_url`, and the copy differs on edge inputs
```
def _slug(url: str) -> str:
    tail = url.rstrip("/").removesuffix(".git")
    return "/".join(tail.replace(":", "/").split("/")[-2:])
```
Both places derive the same fact, the owner/name slug. They split on input: the shared version strips whitespace and returns None for empty or single-segment URLs. The copy returns "" or a bare name, and two empty values compare equal. A URL with trailing whitespace from a hand-edited `.task-id` produces a false mismatch only in the copy.
Fix: use `git.slug_from_url`. Treat a None slug on either side as a WARN row ("no comparable remote"), not as a match.

3. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:28`** — a malformed `.task-id` or a detached HEAD aborts or misreports the whole doctor run
```
meta = json.loads(meta_path.read_text())
```
One corrupt `.task-id` raises `JSONDecodeError` and kills the check for every task. A detached HEAD reports the branch as "HEAD". That is a mismatch, but the message is misleading. Nothing in the files I read (a grep for `.task-id` found no other consumer) shows a handler above this function.
Fix: wrap the per-task body in `try/except (ValueError, OSError, GitError)` and emit a WARN row for that task. Use `current_branch`, which raises on a detached HEAD, to get a clear message.

4. [nit · 3] **`.agent/tools/maintenance/doctor_worktrees.py:7`** — `TASKS` is hard-coded to `Path.home() / ".agent" / "tasks"`
If a tasks-root constant already exists elsewhere, this is a second owner of that path. My grep found no other definition in the files provided, so I can't confirm one. The cost is a path that disagrees with the rest of the tools if the tasks root ever moves.

### Findings: 4