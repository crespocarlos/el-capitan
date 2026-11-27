Assessment: request-changes — `ship` re-derives the repo, base and remote from git state, even though Gate 2 already recorded `repo_remote_url` and `base` in `.task-id`. That gives each fact two owners.
Read beyond the package: .task-id, grep for `repo_remote_url` and `upstream` (the only code hit is task_ship.py itself)

1. [attention · 4] **`.agent/tools/task/task_ship.py:10`** — remote chosen from whatever `upstream` exists, not from the recorded `repo_remote_url`
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
...
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
Gate 2 recorded `repo_remote_url: git@github.com:acme/widgets.git` as the task's repository. `ship` ignores it and trusts the worktree's remotes. Suppose the worktree has an unrelated `upstream` remote, for example one added by a dev or a tool. The draft PR then targets that repo rather than acme/widgets, and nothing compares the result to the recorded value. The push goes to the wrong remote and the PR opens against the wrong repository.
Fix: make `repo_remote_url` the single owner. Select the remote whose URL slug matches the recorded one. For a fork, require that the recorded slug equals the `upstream` slug, and stop if no remote matches. Do not default to `upstream` by its mere existence.

2. [attention · 4] **`.agent/tools/task/task_ship.py:11`** — base re-derived from the spec text or the remote default, ignoring recorded `base`
```
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
`.task-id` records `"base": "main"`, which Gate 2 set. Here the spec's `## Base:` heading or the remote's current default branch overrides it. If the spec is edited after Gate 2, or the default branch changes, the PR targets a different base than the one the branch and tests were built against. Because `ship` merges the base and re-runs tests, those steps then use a base the task never recorded.
Fix: use `task.meta["base"]` as the base and fall back to derivation only when it is absent. Alternatively, fail when the derived value and the recorded value differ.

3. [attention · 3] **`.agent/tools/task/task_ship.py:20`** — `task.repo` is only a fallback, and no recorded value is compared against the target
```
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
The recorded repo is used only when the origin URL cannot be parsed, and never when the remote is `upstream`. So a mismatch cannot be detected, and the guard `refuses when it is not on the task's branch` covers the branch but not the repository. I could not see how `task.repo` is populated, so the check may exist elsewhere.
Fix: after `where_to`, compare `target` with the slug of `repo_remote_url` and return an exit-2 message on mismatch.