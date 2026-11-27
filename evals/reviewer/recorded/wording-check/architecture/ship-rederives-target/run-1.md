Assessment: request-changes — `ship` re-derives the PR's repository and base from live git state and the spec text, and ignores the `repo_remote_url` and `base` that Gate 2 recorded in `.task-id`.

Read beyond the package: `.task-id` (the only other file in the working directory). `task_ship.py` is an excerpt, so I could not check `load`, `SPEC_BASE` or `slug_from_url`.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:16`** — PR target comes from live remotes, not the recorded `repo_remote_url`
```
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
The `.task-id` file records `"repo_remote_url": "git@github.com:acme/widgets.git"`, and Gate 2 owns that fact. `where_to` consults it only when the remote's URL cannot be parsed, and only for `origin`. If the worktree has an `upstream` remote pointing at some other repository, or `origin` was re-pointed after Gate 2, the draft PR opens against that repository instead of `acme/widgets`. A PR opened on the wrong repository is public and cannot be undone. `ship` never compares the derived target with the recorded one, so nothing notices.
Fix: make `task.repo` the owner. Derive `target` from it. Use the remotes only to find which remote name points at that slug, and return exit 2 from `prepare` when none matches or the derived slug differs from the recorded one.

2. [attention · 4] **`.agent/tools/task/task_ship.py:15`** — base re-derived from the spec and the remote default, ignoring the recorded `base`
```
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
`.task-id` records `"base": "main"` at Gate 2. `ship` reads the spec's `## Base:` line, or else the remote's default branch, and never reads `task.meta["base"]`. If the spec is edited after Gate 2, or the default branch is renamed or differs from the recorded base, the PR targets a base that disagrees with the one the task was implemented and tested against. The docstring's "merge the base, re-run the spec's tests" would then merge a different branch from the one Gate 2 recorded. This also hits a fork whose upstream default branch differs from the task's.
Fix: use `task.meta.get("base")` as the base. Fall back to the spec or the default branch only for old `.task-id` files that lack the key, and error on a mismatch.

3. [attention · 3] **`.agent/tools/task/task_ship.py:14`** — remote choice by presence of `upstream`, not by the task
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
```
This picks the fork topology from whatever is configured in the worktree. The recorded repo has no say. If a dev adds an `upstream` remote for unrelated reasons, a task whose repo is `origin` gets a cross-repository PR with an `owner:branch` head, and the branch is pushed to the wrong place. Pushing is not shown in the excerpt; I'm inferring it from the docstring and the `remote` that `Ship` carries.
Fix: choose the remote by matching the recorded slug (finding 1), not by which remote names exist.