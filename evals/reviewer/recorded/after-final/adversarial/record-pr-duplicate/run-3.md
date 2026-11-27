Assessment: request-changes — the matching logic misses cases where the PR hook fires twice or runs for a PR on a closed task, so it can still create duplicate tasks or mislabel existing ones.

Read beyond the package: none (the working directory had no definitions for `append_pr`, `tasks_in`, `head`, `close` or `candidates`, so I could not verify them). Assumption-grounding rests on the diff alone.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:place`** — a repeat hook run for the same branch creates a second DONE task
```
    matches = [r for r in scoped if r.meta.get("branch") == found.branch]
    ...
    return [minimal_task(tasks_dir, found, scoped)] if scoped else []
```
The first run for a spec-less PR writes a minimal task with `branch` set, so a rerun is normally found by `matches`. The problem is the `scoped` filter. `tasks_in(tasks_dir, found.repos)` selects tasks by repo. In `minimal_task`, `owner` is the first scoped task whose repo matches, and the new task copies that task's `repo_remote_url`. If `tasks_in` matches by something other than `repo_remote_url` (for example, the PR URL's repo against a normalised remote), the new task can fall outside `scoped` on the next run. The hook would then see no match and create another task, and each re-fire adds a duplicate. Separately, `uuid4` directories and the `mkdir(parents=True)` call have no lock, so two concurrent hook runs (a retry, or parallel worktrees) both see no match and both create a task.
Fix: Make the match idempotent. Look the branch up across all tasks in the repo before creating one, and take a lock or use a deterministic directory name derived from repo plus branch.

2. [attention · 4] **`.agent/tools/task/task_record_pr.py:minimal_task`** — `next(...)` raises `StopIteration` when no scoped task matches a repo
```
owner = next(r for repo in found.repos for r in scoped if r.repo.lower() == repo)
```
`found.repos` is compared lowercased against `r.repo.lower()`, but `repo` itself is not lowercased here. If `found.repos` holds mixed-case names (`Org/Repo`), nothing matches and `next` raises `StopIteration`. The hook then fails, and the PR is never recorded. `scoped` may also have been matched by a looser rule than this equality.
Fix: `owner = next((r for ... if r.repo.lower() == repo.lower()), None)`, and return `[]` or fall back to the first scoped task when it is `None`.

3. [attention · 3] **`.agent/tools/task/task_record_pr.py:place`** — a PR with a spec on a different branch is recorded as a spec-less DONE task
```
chosen = [r for r in matches if head(r) not in CLOSED] or matches
```
The branch is matched only by exact equality with `meta["branch"]`. `mark-implementing` records `branch` only when `--branch` is passed. A task that went through implementing without `--branch` has no `branch`, and its spec branch is already handled separately. The implementation branch of that task matches neither lookup, so a real PR is recorded as a spec-less DONE task, and the true task stays IMPLEMENTING with no PR attached.
Fix: Warn or report when an IMPLEMENTING task in the same repo lacks `branch`, rather than silently minting a DONE task. Alternatively, make `mark-implementing` always record the current branch.

4. [nit · 3] **`.agent/tools/task/task_record_pr.py:slug_of`** — the slug can collide
The title is truncated to 60 characters and falls back to `"pr"`. Two spec-less PRs with similar titles get identical slugs on different tasks. This costs ambiguous `crew ls` output if the slug is used as a key.