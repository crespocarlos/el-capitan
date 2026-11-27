Assessment: request-changes — the check is the right feature, but it bypasses the shared git module whose contract exists to prevent the false answers this code produces.

Read beyond the package: `.agent/tools/lib/git.py` (already in the package), plus a grep for other consumers of `doctor`, `_slug` and `.task-id`. Grep found no other consumers and no registration of `check_worktrees` in `crew doctor`.

Approach: redirect — build the check on `lib/git.py` (`current_branch`, `remote_url`, `slug_from_url`, `GitError`) rather than a private `_git` and `_slug`.
Alternatives considered:
- Use the shared `lib/git.py` helpers and turn `GitError` into a WARN row — this wins. It is the established single door to git, it is smaller, and it makes failures visible.
- Keep the private `_git` helper — this loses. It duplicates the module and drops the "empty output is never an answer" rule.
- Don't build the check — this loses. A doctor check for stale worktrees is a real need, and nothing existing covers it.

1. [blocking · 5] **`.agent/tools/maintenance/doctor_worktrees.py:12`** — `_git` uses `check=False` and returns empty stdout on any git failure, so a broken worktree reads as a plain mismatch
```
result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
return result.stdout.strip()
```
The shared module says "Every helper raises `GitError` when git cannot answer; empty output is never read as an answer". Take a worktree directory that exists but is not a repository, which is what a half-deleted worktree looks like. `branch` comes back as `""`, so the report says "is on , not feature-x". `origin` is `""`, so it says "(none)". Git's real failure (not a repository, git missing, a hang) is lost, and there is no timeout, so one hung repository stalls `crew doctor`. A detached HEAD is reported as being on "HEAD", which is misleading.
Fix: Drop `_git`. Call `git.current_branch(tree)` and `git.remote_url(tree)` inside `try/except GitError`. On error, append a WARN row that carries the error text and `continue`.

2. [attention · 5] **`.agent/tools/maintenance/doctor_worktrees.py:17`** — `_slug` is a second copy of `slug_from_url`, and the two differ
```
def _slug(url: str) -> str:
    tail = url.rstrip("/").removesuffix(".git")
    return "/".join(tail.replace(":", "/").split("/")[-2:])
```
The shared `slug_from_url` handles None and empty input, strips whitespace, and returns None when there are fewer than two parts. This copy does none of that, so the two disagree on the first odd input. A task missing `repo_remote_url` makes `_slug("")` return `""`, and an origin of `""` also gives `""`. The two compare equal and the check passes silently. A missing origin therefore goes unreported exactly when the task metadata is also missing the URL.
Fix: Use `git.slug_from_url`. Treat a None slug on either side as its own WARN ("task has no repository recorded" or "no origin") rather than comparing None to None.

3. [attention · 4] **`.agent/tools/maintenance/doctor_worktrees.py:28`** — one malformed `.task-id` crashes the whole doctor run
```
meta = json.loads(meta_path.read_text())
```
A truncated or invalid `.task-id` raises `JSONDecodeError`. The checker stops and no task is reported, so the diagnostic tool fails on exactly the corrupt state it is meant to diagnose.
Fix: Catch `(OSError, ValueError)` around the read and emit a WARN row for that task, then continue.

4. [attention · 3] **`.agent/tools/maintenance/doctor_worktrees.py:8`** — `TASKS` is hard-coded as `~/.agent/tasks`, and `check_worktrees` is not wired into `crew doctor`
The grep found no caller of `check_worktrees` and no other definition of the tasks root. If the tools already resolve the tasks directory somewhere else, this is a second owner of that path.
Fix: Reuse the tools' existing tasks-root resolution if there is one, and register the check in the doctor runner.

### Findings: none

Correction: the closing `### Findings: none` line above is wrong, because findings 1–4 are listed. Please ignore that line.