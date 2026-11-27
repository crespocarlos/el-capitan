Assessment: request-changes — a PR is matched to its task only by `branch`, and `mark-implementing` doesn't always record `branch`. Those PRs fall through to a duplicate DONE task.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:47`** (`place`) — an unmatched PR creates a duplicate DONE task, even when a task already has the PR or is still IMPLEMENTING
```python
    return [minimal_task(tasks_dir, found, scoped)] if scoped else []
```
`place` matches only on `meta["branch"]` and `meta["spec_branch"]`. The change description says `mark-implementing` records `branch` only when `--branch` is passed. An IMPLEMENTING task started without `--branch` therefore never matches. Its PR gets a second, fake "no spec" DONE task, and the real task never gets the PR or the DONE gate. The same happens when the orchestrator already ran `mark-done --pr-url <url>` by hand on a task with no `branch`. In that case the hook's `minimal_task` call adds a duplicate, and `crew ls` shows two tasks for one PR. A re-fired hook is covered only if the first run recorded `branch`. `minimal_task` does no idempotency check either: nothing looks for `found.url` in any scoped task's PR list before it creates a task.
Fix: before `minimal_task`, scan `scoped` for any task whose PR list already contains `found.url` and return "already has". Consider a fallback that matches on slug or an IMPLEMENTING task that has no `branch`, instead of fabricating a task. This is introduced by the diff.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:27`** (`minimal_task`) — `next(...)` can raise `StopIteration` and abort the hook
```python
owner = next(r for repo in found.repos for r in scoped if r.repo.lower() == repo)
```
`scoped` comes from `tasks_in(tasks_dir, found.repos)`. If that function matches repos differently from `r.repo.lower() == repo`, for example because it doesn't lowercase `found.repos` or normalizes remote URLs, the generator is empty. `next` then raises `StopIteration`. The hook fails after `gh pr create`, and the PR is never recorded. I could not read `tasks_in`, so this assumption is unverified.
Fix: use `next(..., None)` and return `[]` or a message when no owner is found.

3. [attention · 3] **`.agent/tools/task/task_record_pr.py:28`** (`minimal_task`) — a crash partway through leaves a half-built task directory
```python
directory.mkdir(parents=True)
...
atomic_write(directory / ".task-id", ...)
```
The directory is created first, then `.task-id`, then `SPEC.md`, then `append_pr`. If a later step fails, a directory is left behind with `.task-id` but no SPEC.md (or no PR). `crew ls` may then choke on it or show it with "no status". Because `head(r)` is blank, `place` treats such a task as not closed on the next run, so the next hook run appends to the broken task and never replaces it.
Fix: build the task in a temp directory and `rename` it into place, or clean up on exception.