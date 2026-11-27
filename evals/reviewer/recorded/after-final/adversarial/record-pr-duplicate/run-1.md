Assessment: request-changes — `place()` matches tasks only by `branch`, but `mark-implementing` doesn't always record `branch`. A PR for a real task can therefore get a second, spec-less DONE task.

Read beyond the package: none. The working directory has only this excerpt. A grep for `append_pr`, `tasks_in`, `head`, `close` and `candidates` found no definitions.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:47`** (h1) — a PR for a task with no recorded `branch` gets a duplicate DONE task
```python
    drafted = [r for r in scoped if r.meta.get("spec_branch") == found.branch]
    ...
    return [minimal_task(tasks_dir, found, scoped)] if scoped else []
```
The change description says `mark-implementing` records `branch` only when `--branch` is passed. Take an IMPLEMENTING task started without `--branch` and open its PR. `matches` is empty and `drafted` is empty, so the hook creates a minimal DONE task, "opened with no spec". The real task stays IMPLEMENTING with no PR, and `crew ls` shows one PR on two tasks. When the orchestrator later runs `mark-done --pr-url <url>`, the real task also records that PR, so the PR now sits on both tasks. The same happens if the order is reversed. Nothing checks whether any task already lists `found.url`.
Fix: before creating a minimal task, scan `scoped` for any task whose PR list already contains `found.url` and treat it as the match. Also consider matching an IMPLEMENTING task by repo and a unique worktree or branch heuristic. Alternatively have `mark-implementing` always record the current branch.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:30`** (h1) — no idempotence across tasks, and the minimal task is created without a lock
```python
directory = tasks_dir / str(uuid.uuid4()).upper()
directory.mkdir(parents=True)
```
If the hook fires twice at nearly the same time, for example from a retry or two parallel `gh pr create` calls, both runs can read `matches` as empty before either writes `.task-id`. Each run then makes its own DONE task for the same URL. Sequential reruns are safe because the second run matches on `branch`. The window is the gap between `tasks_in` and `atomic_write`.
Fix: take a lock on `tasks_dir` around `place()`, or re-check for a task with this URL or branch immediately before `mkdir`.

3. [attention · 3] **`.agent/tools/task/task_record_pr.py:31`** — `next()` with no default can raise `StopIteration`, and the minimal task is half-built on failure
```python
owner = next(r for repo in found.repos for r in scoped if r.repo.lower() == repo)
```
`scoped` comes from `tasks_in(tasks_dir, found.repos)`. If that function matches repos differently from the `.lower()` comparison here, for example a case or remote-URL normalization difference, `next` raises. The hook then crashes after `place()` has decided to create a task. Separately, `mkdir` runs before the writes, so a failure in `atomic_write` leaves an empty UUID directory. `tasks_in` may then trip on it, or `crew ls` may show a task with no `.task-id`.
Fix: use `next(..., None)` and return `[]` or a message when it is `None`. Build the files in a temp directory and rename it into place, or remove the directory on error.

4. [nit · 3] **`.agent/tools/task/task_record_pr.py:12`** — the slug is not unique, and `mark-done` can't use it to find the task
`slug_of` is derived from the PR title, so two spec-less PRs with the same title produce tasks with the same slug. If a CLI command looks tasks up by slug, it will hit an ambiguity. The cost is limited to `crew-task.py` commands that take a slug, and there is no uniqueness check here.