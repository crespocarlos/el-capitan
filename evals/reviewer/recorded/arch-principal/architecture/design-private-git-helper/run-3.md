Assessment: request-changes — the new module re-implements the shared git helpers, and its `_git` turns git failures into empty strings, which the shared module explicitly forbids.

Read beyond the package: none (`.agent/tools/lib/git.py` was the one file read). A grep for other doctor wiring or consumers found only this file, so I could not see how `check_worktrees` is registered.

Approach: redirect — build the check on `lib/git.py` (`current_branch`, `remote_url`, `slug_from_url`, `GitError`) instead of a private `_git` and `_slug`.
Alternatives considered:
- Don't build it / use what exists: `lib/git.py` already provides every primitive the check needs, so only the comparison logic is new. This wins, and it is the recommended route.
- Keep the private `_git` and `_slug`: this is the smallest diff today. It loses because it creates a second git door with the opposite failure semantics, and a second copy of the slug rule.
- A generic "verify task invariants" framework: this is over-built for one check and loses.

1. [blocking · 5] **`.agent/tools/maintenance/doctor_worktrees.py:13`** — `_git` turns git failures into an empty string, so the check reports the wrong cause
```
result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
return result.stdout.strip()
```
A recorded worktree directory that exists but is no longer a repository (a deleted `.git`, or git not installed) makes `rev-parse` fail and return "". The row then says "is on , not feature-x". If the remote is also missing, the row says "origin (none)". A git failure and a legitimately empty answer look the same, and `lib/git.py` says "empty output is never read as an answer". There is also no timeout, so a hung git call (for example on a network-mounted worktree) stalls the whole `crew doctor` run.
Fix: import `GitError, current_branch, remote_url` from `lib/git.py`. Catch `GitError` per task and emit a distinct WARN such as "{name}: {tree} is not a usable git repository: {error}".

2. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:17`** — `_slug` duplicates `slug_from_url` and handles fewer inputs
```
def _slug(url: str) -> str:
    tail = url.rstrip("/").removesuffix(".git")
    return "/".join(tail.replace(":", "/").split("/")[-2:])
```
The rule for turning a remote URL into `owner/name` now lives in two places. They differ on input: `slug_from_url` returns None for empty or one-segment input, while `_slug("")` returns "". If `repo_remote_url` is missing and origin is missing, both slugs are "", so they compare equal and the check passes silently. The task has no repository recorded and no origin, and that is exactly the case that should be flagged. Surrounding whitespace is also not stripped.
Fix: use `slug_from_url`, and treat a None slug on either side as a mismatch, or as a separate "no repository recorded" WARN.

3. [attention · 3] **`.agent/tools/maintenance/doctor_worktrees.py:30`** — one malformed `.task-id` aborts the whole doctor run
```
meta = json.loads(meta_path.read_text())
```
A single corrupt or half-written `.task-id` raises `JSONDecodeError`. `crew doctor` then crashes without checking any other task, when it should report that one task as a WARN. Doctor exists to surface this kind of damage. I did not see how the caller handles exceptions, so I rate this 3.
Fix: wrap the read and parse in `try/except (OSError, ValueError)` and append a WARN row for that task.

4. [attention · 3] **`.agent/tools/maintenance/doctor_worktrees.py:35`** — a detached HEAD and a branch mismatch are reported as the same thing
```
branch = _git(tree, "rev-parse", "--abbrev-ref", "HEAD")
if branch != meta.get("branch"):
```
A detached HEAD makes `--abbrev-ref` print "HEAD", so the row reads "is on HEAD, not feature-x". `current_branch` already raises a `GitError` for this case. Once finding 1 is fixed, that error gives a clear "detached HEAD" row.
Fix: use `current_branch` and handle its `GitError` as part of finding 1.