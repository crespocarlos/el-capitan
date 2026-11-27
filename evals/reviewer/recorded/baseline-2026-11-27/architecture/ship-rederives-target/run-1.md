Assessment: request-changes — `where_to` re-derives the target repo and base from git remotes and spec text. Gate 2 already recorded both in `.task-id`, and `ship` never checks them against the result.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:15`** (target derivation) — the PR target ignores the repo that Gate 2 recorded
```
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
`.task-id` records `repo_remote_url` (`git@github.com:acme/widgets.git`), but it is only a fallback here, and only for `origin`. If the worktree has an `upstream` remote, or an `origin` that points elsewhere, the live remote wins. The commit is pushed and the draft PR opened against whatever the remote says, not the repo the task was approved for. Nothing compares the two, so a mismatch ships silently. This is a pre-flight contract check that the change describes but does not perform.
Fix: Treat `task.repo` as the source of truth. Normalise it with `slug_from_url`, pick the remote whose slug matches it (`upstream`, then `origin`), and return a `prepare` error string if none match. Drop the silent fallback.

2. [attention · 4] **`.agent/tools/task/task_ship.py:14`** — the base is re-derived instead of read from the recorded `base`
```
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
`.task-id` has `"base": "main"` and `spec_branch`, recorded at Gate 2. This code instead greps the spec text for `## Base:` or asks the remote for its default branch. If the spec was edited after Gate 2, or the remote's default branch changed, `ship` merges and targets a different base than the one the task was implemented against. The merge-base and test re-run step then validates against the wrong branch. There are now two sources of truth for the base, and they can disagree.
Fix: Use `task.meta["base"]` when present. Fall back to the `## Base:` match or the remote default only for legacy tasks that have no recorded base.

3. [attention · 3] **`.agent/tools/task/task_ship.py:20`** — the fork head ref depends on `origin` resolving and is skipped silently when it does not
```
return remote, base, target, f"{owner}:{branch}" if owner else branch
```
When `upstream` exists but the `origin` slug cannot be parsed, the head ref falls back to a bare `branch`. A cross-repo PR against `upstream` then fails, or worse, resolves to a same-named branch in the target repo. The `Stop` guard covers only `target`, not `owner`.
Fix: Raise `Stop` when `remote != "origin"` and `owner` is empty.

4. [nit · 3] **`.agent/tools/task/task_ship.py:29`** — `prepare` validates the branch and worktree against the record but not the repo
The checks on worktree and branch are good. Adding the same check for the repo after `where_to` (recorded slug equals target slug) would make finding 1 a single assertion. Without it, the three recorded fields are not validated consistently.