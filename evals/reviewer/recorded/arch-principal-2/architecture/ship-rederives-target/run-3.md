Assessment: request-changes — `ship` re-derives the repo, base and target from the worktree's git remotes and the spec text, although gate 2 already records them in `.task-id`.
Read beyond the package: none (the package holds only `.task-id` and the excerpt).

Approach: redirect — read the target and base from the `.task-id` fields that gate 2 recorded, and verify the worktree against them, rather than guessing them again from git state.
Alternatives considered:
- Use the recorded `repo_remote_url` and `base` from `.task-id`, and check that the worktree's remote matches — this wins. It gives one owner for each fact, and a mismatch fails loudly instead of opening a PR against the wrong repository.
- Keep re-deriving, as the diff does — this loses. The `upstream` heuristic, the spec's `## Base:` regex and `default_branch` can each disagree with what gate 2 recorded.
- Don't build `ship` and keep commit, push and PR as manual steps — this leaves the one-step ship unmet. It is not needed once the recorded values are used.

Next changes:
- Supporting a new remote layout, such as a differently named fork remote, would mean editing `where_to`. If the target is recorded, only gate 2 changes.
- Changing the base after gate 2 would mean the spec and `.task-id` disagree, and `ship` would silently follow the spec.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:11`** — target and base are re-derived instead of read from `.task-id`
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
`.task-id` records `repo_remote_url` (`git@github.com:acme/widgets.git`) and `base` (`main`). Here the worktree has an unrelated `upstream` remote, for example a personal mirror. `ship` then targets that repository and ignores the recorded `acme/widgets`. If the spec has a `## Base: develop` line while gate 2 recorded `main`, the PR goes to `develop`. Each value now has two owners, and the PR can be opened against the wrong repository or branch.
Fix: take `target` from `slug_from_url(task.meta["repo_remote_url"])` and `base` from `task.meta["base"]`. Use the remotes only to pick the push remote, by finding the remote whose URL matches the recorded repository, or the fork whose upstream does. If none matches, stop with a message.

2. [attention · 3] **`.agent/tools/task/task_ship.py:12`** — `task.repo` is a fallback only when the remote is `origin`
```
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
The recorded value is used only when the remote URL cannot be parsed, so it never overrides git state. It also hides a worktree whose `origin` was repointed. `ship` would push to the wrong place, where it should refuse.
Fix: compare the recorded slug with the remote's slug and return an error from `prepare` when they differ.