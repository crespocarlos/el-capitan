Assessment: request-changes — `ship` re-derives the PR target and base from live git remotes and spec text. It ignores the `repo_remote_url` and `base` that Gate 2 recorded, so the PR can land in the wrong repository or against the wrong branch.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:12`** — PR target is derived from worktree remotes, not the recorded `repo_remote_url`
```python
remote = "upstream" if remote_url(tree, "upstream") else "origin"
...
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
Gate 2 records `repo_remote_url` (`git@github.com:acme/widgets.git` in `.task-id`) as the task's repository. `ship` uses it only as a fallback, and only when the remote is `origin` and its URL doesn't parse. Any `upstream` remote in the worktree takes precedence. That includes a stale remote, one added by hand, or one inherited from a shared clone. The commit, push and draft PR then go to a repository the task never named. `ship` never checks that the chosen remote matches the recorded repo. Gate 2 already checks that the branch matches. The same check is missing for the repo, so the two are inconsistent. The cost is a pushed branch and an opened PR in the wrong repository, which is hard to undo.
Fix: make the recorded `task.repo` the source of truth. Pick the remote whose URL slug equals `slug_from_url(task.repo)`. If no remote matches, return a "worktree remotes don't match the task's repo" error from `prepare` (exit 2). Only treat a fork layout as valid when `upstream` matches the recorded repo and `origin` is the fork.

2. [attention · 4] **`.agent/tools/task/task_ship.py:13`** — the recorded `base` is ignored
```python
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
`.task-id` carries `base` (`main`), written at Gate 2. `ship` re-reads the spec's `## Base:` line and otherwise falls back to the remote's default branch. If the spec is edited after Gate 2, or the default branch differs from the recorded base, the "merge the base, re-run tests" step and the PR target use a different base than the one the task was implemented against. The tests then pass against the wrong base.
Fix: use `task.meta.get("base")` first. Fall back to the spec or default branch only when it is absent, and fail if the two disagree.

3. [nit · 2] **`.agent/tools/task/task_ship.py:19`** — fork head ref depends on `origin`'s owner
```python
owner = (slug_from_url(remote_url(tree, "origin")) or "").split("/")[0]
return remote, base, target, f"{owner}:{branch}" if owner else branch
```
When `owner` can't be parsed, this silently falls back to a bare branch name. For a fork PR, the PR will then fail or attach to the wrong head. Raising `Stop` here would be consistent with `where_to`'s own docstring.