Assessment: request-changes — `ship` re-derives the target repo and base from git remotes and spec text, although Gate 2 already recorded both in `.task-id`.

Read beyond the package: `.task-id` (the only other file in the working directory).

1. [attention · 4] **`.agent/tools/task/task_ship.py:12`** — PR target is derived from live remotes, not the repo recorded at Gate 2
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
...
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
`.task-id` records `"repo_remote_url": "git@github.com:acme/widgets.git"`, but `ship` uses it only as a fallback, and only when the remote is `origin`. Suppose the worktree has an `upstream` remote that points at a different repo than the task's, such as a stale remote or a fork of a fork. The draft PR then opens against that repo, and nothing compares it with the recorded one. Gate 2 owns the repository fact and `ship` keeps a second copy.
Fix: Treat `task.repo` as the source of truth. Find the remote whose slug equals it and target that slug. Raise `Stop` when no remote matches or when the derived target differs from the recorded one.

2. [attention · 4] **`.agent/tools/task/task_ship.py:13`** — base ignores the `base` recorded in `.task-id`
```
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
`.task-id` has `"base": "main"`, which `mark-implementing` recorded. Suppose the spec has no `## Base:` line and the remote's default branch is `develop`. The PR then targets `develop`. The branch was cut from `main`, so the diff carries unrelated commits. This also feeds the "merge the base, re-run tests" step in the module docstring, so the wrong base gets merged too. If the spec's `## Base:` is edited after Gate 2, it also changes the base.
Fix: Use `task.meta.get("base")` first. Fall back to the spec or the default branch only when it is absent, and warn when the two disagree.

3. [needs more info · 2] **`.agent/tools/task/task_ship.py:11`** — does `task.repo` read `repo_remote_url`?
The code reads `task.repo`, and `.task-id` stores the field as `repo_remote_url`. I could not see `load()` or `TaskState`, so I don't know whether `task.repo` is a URL or a slug. `slug_from_url` is applied to remotes but not to `task.repo`. If `task.repo` holds the raw SSH URL, `target` becomes `git@github.com:acme/widgets.git` and `gh pr create --repo` fails. Does `TaskState.repo` hold a slug, and which `.task-id` key does it map to?