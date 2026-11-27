Assessment: request-changes — `ship` re-derives the PR target and base from the worktree's git remotes instead of using the `repo_remote_url` and `base` that Gate 2 recorded, so the PR can land in the wrong repository.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:14`** (the `where_to` target derivation) — PR target ignores the recorded `repo_remote_url`
```python
remote = "upstream" if remote_url(tree, "upstream") else "origin"
...
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
Gate 2 records the task's repository in `.task-id` (`"repo_remote_url": "git@github.com:acme/widgets.git"`). `where_to` uses that value only as a fallback, and only when the remote is `origin` and its URL can't be parsed. If the worktree has an `upstream` remote, the PR goes to `upstream`'s repository whether or not it matches the task's repo. A worktree on the same branch but cloned from a different repository would push and open a PR against the wrong repo, and the branch check in `prepare` would not catch it. The recorded value is meant to be the source of truth, so the mismatch should be refused, not silently resolved. Fix: derive `target` from `task.repo` and verify that the chosen remote's slug matches it. Pick the remote by matching slugs, and raise `Stop` on a mismatch. Keep the fork heuristic only to choose which remote to push to.

2. [attention · 4] **`.agent/tools/task/task_ship.py:13`** (h1) — Base is re-derived and the recorded `base` is ignored
```python
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
Gate 2 records `"base": "main"` in `.task-id`, alongside `spec_branch`. `ship` takes the base from a regex over the spec text, or from the remote's current default branch. The merge-the-base step and the PR base can therefore differ from what the task was implemented against. This happens if the spec's `## Base:` changed after Gate 2, or if the default branch was renamed or points elsewhere on `upstream`. This is a second source of truth for the same fact. Fix: use `task.meta["base"]` and fall back to the derivation only when it is absent. I could not confirm whether `Ship` or `load` already reconciles the two.

3. [attention · 3] **`.agent/tools/task/task_ship.py:30`** — Branch guard checks the branch but not the repository
```python
actual = current_branch(tree)
if not branch or actual != branch:
```
`prepare` validates the worktree's branch against the recorded one but never checks the worktree's repository against `repo_remote_url`. Branch names like `feat/...` are easy to repeat across repositories. The guard is therefore weaker than the "refuses when not on the task's branch" contract implies, and it is the only check before commit and push. Fix: add a check here that some remote's slug equals the slug of `task.repo`, and return an exit-2 message when none does. This also gives finding 1 a single place to be enforced.