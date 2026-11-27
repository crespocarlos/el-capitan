Assessment: request-changes — matching depends on `meta["branch"]`, which `mark-implementing` doesn't write unless `--branch` is passed. An ordinary spec'd task is therefore missed and gets a duplicate DONE task.

Read beyond the package: grep of the working directory. Only `task_record_pr.py` exists, so `append_pr`, `head`, `tasks_in`, `close`, `candidates` and `mark-implementing` are unverified. Assumption-grounding rests on the diff alone.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:35` (h1)** — A task implemented without `--branch` never matches, so the PR gets a duplicate minimal DONE task
```
matches = [r for r in scoped if r.meta.get("branch") == found.branch]
...
return [minimal_task(tasks_dir, found, scoped)] if scoped else []
```
The change says `mark-implementing` records `branch` only when `--branch` is passed. Take a spec'd task that is IMPLEMENTING with no `branch` in `.task-id`. The orchestrator opens its PR, and `matches` comes back empty. The `spec_branch` check also misses, since the PR is not on the spec branch. The code then falls through to `minimal_task`, which creates a second task for the same work with status DONE and a "no spec" summary. The real task stays IMPLEMENTING and never gets the PR or the DONE gate, and `crew ls` shows two entries. Any repo that already has tasks hits this on every PR from a task started without `--branch`. The "PR opened with no spec" case cannot be told apart from "spec'd task with no recorded branch".
Fix: before creating a minimal task, check for an IMPLEMENTING task in the same repo that has no `branch` (or whose slug matches the branch). If exactly one exists, adopt it and set `branch`; if more than one, return `candidates(...)`. Alternatively, make `mark-implementing` always record the current git branch.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:15` (h1)** — `next(...)` with no default raises `StopIteration`, and the hook dies without recording anything
```
owner = next(r for repo in found.repos for r in scoped if r.repo.lower() == repo)
```
This assumes every entry in `found.repos` is already lowercase and that `scoped` rows carry a matching `.repo`. If `tasks_in` normalises differently (an owner/name versus a bare-name remote, or a case difference), the generator is empty. A bare `StopIteration` then propagates out of a PostToolUse hook, with no message saying which PR was skipped.
Fix: use `next(..., None)`, and when it is `None`, return a `record-pr: could not resolve repo for {found.url}` line (or fall back to `scoped[0]`).

3. [attention · 3] **`.agent/tools/task/task_record_pr.py:17-23` (h1)** — The minimal task is created in several steps with no rollback, and two hook runs can race
```
directory.mkdir(parents=True)
...
atomic_write(directory / ".task-id", ...)
atomic_write(directory / "SPEC.md", ...)
```
The directory name is a fresh UUID, so there is no lock and the check-then-create is not atomic. Two hook invocations for the same branch, such as a retry or a double fire, both see no match and both create a DONE task. A crash between the `.task-id` write and the `SPEC.md` write leaves a task with no status. `head()` then returns empty, which is not in `CLOSED`, so later runs treat it as an open match.
Fix: take a per-repo or per-branch lock around `place`, and write `SPEC.md` before `.task-id` (or build the directory under a temporary name and rename it).