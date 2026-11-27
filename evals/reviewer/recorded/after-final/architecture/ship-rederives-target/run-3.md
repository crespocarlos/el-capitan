Assessment: request-changes — `ship` re-derives the repo, base and remote from git state, although Gate 2 already recorded them in `.task-id`. The PR can therefore target a different repo than the task's.

Read beyond the package: `.task-id`, plus a grep for `repo_remote_url` and `upstream`. The grep found no other consumers in the working directory.

1. [attention · 4] **`.agent/tools/task/task_ship.py:10`** (h1) — Remote and target are re-derived from the worktree's git remotes, not from the recorded `repo_remote_url`
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
...
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
The `.task-id` records `repo_remote_url` as `git@github.com:acme/widgets.git`, and Gate 2 owns that fact. `where_to` ignores it whenever a remote URL resolves. Suppose the worktree has an `upstream` remote pointing at a different repo, for example one added by hand or inherited from a clone. `ship` then pushes and opens the PR against that repo instead of `acme/widgets`. The recorded value is only a fallback, and only for `origin`. A task with a recorded repo and a mismatched remote should stop the run, not open a PR somewhere else.
Fix: Compare the slug of `task.repo` (`repo_remote_url`) with each remote's slug. Pick the remote that matches. Raise `Stop` when none matches, or when the chosen remote's slug differs from the recorded one.

2. [attention · 3] **`.agent/tools/task/task_ship.py:11`** (h1) — The base has two owners; Gate 2's recorded `base` is ignored
```
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
`.task-id` records `"base": "main"` and `"spec_branch"`. `ship` re-reads `## Base:` from the spec text and otherwise falls back to the remote's default branch. If the spec has no `## Base:` line and the remote default is not the recorded base (for example `develop` against recorded `main`), the PR targets `develop`, even though the task was branched from `main`. The merge-base step and the spec-test re-run would then use the wrong base too.
Fix: Read `task.meta["base"]` first. Use the spec's `## Base:` or the remote default only when it is absent. Stop if they disagree.

3. [attention · 3] **`.agent/tools/task/task_ship.py:21`** (h1) — The worktree path and branch checks trust `.task-id`, but the head ref owner is derived from the `origin` URL
```
owner = (slug_from_url(remote_url(tree, "origin")) or "").split("/")[0]
return remote, base, target, f"{owner}:{branch}" if owner else branch
```
In the fork case, if `origin` has no parseable URL, the head ref falls back to the bare `branch`. A cross-repo PR then fails, or it matches a same-named branch in the upstream repo. The failure is silent at this layer.
Fix: Raise `Stop` in the fork case when the owner cannot be derived, rather than falling back to the bare branch.