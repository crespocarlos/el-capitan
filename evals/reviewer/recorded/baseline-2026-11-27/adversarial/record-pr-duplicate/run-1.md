Assessment: request-changes — the hook looks tasks up only by `branch`, but `mark-done --pr-url` and `mark-implementing` without `--branch` leave tasks with no `branch`. A hand-closed PR therefore gets a duplicate DONE task.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:40`** (place) — PR already recorded on a task with no `branch` gets a duplicate minimal DONE task
```python
matches = [r for r in scoped if r.meta.get("branch") == found.branch]
...
return [minimal_task(tasks_dir, found, scoped)] if scoped else []
```
The change says `mark-implementing` records `branch` only when `--branch` is passed, and `mark-done --pr-url` records the PR in the task's PR list without setting `branch`. For those tasks, `matches` is empty. The task isn't a `spec_branch` match either. So `place` falls through to `minimal_task` and creates a second DONE task for the same PR. The hook can fire after the orchestrator has already closed the task by hand, and `crew ls` then shows the PR twice. Worse, an IMPLEMENTING task started without `--branch` stays open, because nothing closes it. The idempotency check (`append_pr` returning false) only runs against the branch-matched task, not against any task that already lists `found.url`.
Fix: before the `spec_branch` and minimal-task fallbacks, scan `scoped` for any task whose PR list already contains `found.url`, and return "already has" for it. Optionally, when exactly one IMPLEMENTING task has no `branch`, treat it as a candidate instead of creating a new task.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:19`** (minimal_task) — `next(...)` with no default can raise `StopIteration`
```python
owner = next(r for repo in found.repos for r in scoped if r.repo.lower() == repo)
```
This compares `r.repo.lower()` to `repo` without lowercasing `repo`. If `found.repos` has any mixed-case entry, or `tasks_in` matches repos differently (for example by remote URL normalization), no task matches. `next` then raises `StopIteration` inside a PostToolUse hook, and the PR is silently left unrecorded.
Fix: compare `repo.lower()` on both sides, and use `next(..., None)`. If it returns `None`, return a clear "no owning repo" message or fall back to `scoped[0]`.

3. [nit · 3] **`.agent/tools/task/task_record_pr.py:21`** (minimal_task) — non-atomic creation of the task directory
```python
directory.mkdir(parents=True)
...atomic_write(directory / ".task-id", ...)
atomic_write(directory / "SPEC.md", ...)
```
If the `SPEC.md` write or `append_pr` fails, the task is left half-built. The `.task-id` branch is already set, so later hooks match it, and `head(r)` is empty ("no status"). Fix: build the task in a temp directory and rename it, or write `SPEC.md` before `.task-id`.