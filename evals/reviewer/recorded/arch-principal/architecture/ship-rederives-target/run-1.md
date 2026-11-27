Assessment: request-changes — `ship` works out the PR's target repository and base from the worktree's git remotes and the spec text. Gate 2 already recorded both in `.task-id`, and `ship` ignores those values.
Read beyond the package: `.task-id` (the only other file in the working directory)

Approach: redirect — `ship` should read `repo_remote_url` and `base` from `.task-id`, which gate 2 recorded for exactly this purpose. It should then check that the worktree agrees with them.
Alternatives considered:
- Re-derive from git remotes and the spec (the chosen design) — it needs no state, but it forms a second opinion on a decision gate 2 already made and recorded. It loses.
- Use the recorded `repo_remote_url` and `base`, and verify the worktree's remotes against them — this has one owner for the fact and fails loudly on drift. It wins.
- Hand the commit, push and PR steps to `gh pr create` with `--repo` and `--base` taken from the record — this removes the fork-head-ref logic. It is a smaller version of the winning option. I only partly considered it, because fork handling is still needed.

Next changes and their cost:
- Supporting another remote layout, such as a fork with a differently named remote, means editing the `upstream`/`origin` heuristic in `where_to`. Under the recorded approach, nothing changes.
- Changing how the base is chosen means changing both the gate-2 code and `where_to`. The two will drift.
- Retargeting a task to a different base needs the spec edited as well as `.task-id`. The two can then disagree.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:11`** — PR target repository is re-derived from remotes instead of read from the recorded `repo_remote_url`
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
...
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
The task recorded `git@github.com:acme/widgets.git`. If the worktree has an `upstream` remote that points somewhere else, the draft PR opens against that repository and not `acme/widgets`. Examples are a stale remote or a remote the developer added by hand. Nothing compares the result with the record. `task.repo` is used only as a fallback, and only for `origin`. Two owners of one fact give a silent wrong-repo PR on the first worktree whose remotes differ from what gate 2 saw.
Fix: take `target` from `task.repo`. Find the remote whose URL slug matches it and push to that remote. Raise `Stop` if no remote matches, or if `upstream` names a different slug.

2. [attention · 4] **`.agent/tools/task/task_ship.py:12`** — Base is re-derived from the spec or the remote default, not the recorded `base`
```
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
`.task-id` records `"base": "main"`. If the spec has no `## Base:` line and the remote's default branch is `develop`, `ship` merges `develop` and opens the PR against `develop`. The branch was cut from `main`. The merge-and-test step then pulls in unrelated history.
Fix: use `task.meta["base"]`. Fall back to the spec or the default branch only when the record has no base, and warn when the two disagree.

3. [attention · 3] **`.agent/tools/task/task_ship.py:18`** — Fork head ref uses the `origin` owner, with no check that the push remote is the user's fork
```
owner = (slug_from_url(remote_url(tree, "origin")) or "").split("/")[0]
return remote, base, target, f"{owner}:{branch}" if owner else branch
```
When `owner` is empty, the head ref falls back to the bare `branch`. That is wrong for a cross-repository PR, and it fails later at PR creation. The `upstream` branch of `where_to` also returns `remote="upstream"`, and `remote` is a field of `Ship`. If that field is also the push remote, the push goes to the upstream repository. I could not see how `Ship` uses it, so the push-remote part is a lower-confidence reading.
Fix: return a separate push remote (`origin`). Raise `Stop` when `owner` cannot be determined for a fork.