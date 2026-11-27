Assessment: request-changes — `ship` re-derives the target repo and base from git remotes and spec text, although Gate 2 already recorded them in `.task-id`.
Read beyond the package: none (the only other file was `.task-id`, which I read.)

Approach: redirect — `ship` should read `repo_remote_url` and `base` from `.task-id`, which Gate 2 already recorded. It should verify that the worktree's remotes match, and fail if they don't.
Alternatives considered:
- Use the recorded `.task-id` values and validate them against the remotes. This wins: one owner for each fact, and a mismatch becomes a loud stop instead of a PR opened against a guessed repo.
- Keep re-deriving, as the diff does. This loses: it duplicates Gate 2's decision, and the two copies can disagree.
- Don't build `ship` as one step, and leave commit, push and `gh pr create` to the agent. This loses: the refusal checks (right branch, right repo) are the point of the command, and they need to be in code.

1. [attention · 4] **`.agent/tools/task/task_ship.py:15`** — target repo and base are re-derived instead of read from `.task-id`
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
`.task-id` records `repo_remote_url` (`acme/widgets`) and `base` (`main`). `where_to` uses neither of them as the source of truth. `task.repo` is only a fallback, and only when the remote is `origin`.

Failure scenarios:
- If the worktree has an `upstream` remote pointing at a different repo, such as a fork of a fork or a mirror, the draft PR opens against that repo while the task says `acme/widgets`.
- If the spec's `## Base:` line is edited after Gate 2, or is missing and the remote's default branch is `develop`, the PR targets a different base than the one the task recorded. The same worktree was also merged and tested against the recorded base.

Nothing compares the derived values with the recorded ones. This code is new in the diff.

Fix: Take `target` from `task.repo` and `base` from `task.meta["base"]`. Use the remotes only to find which remote name matches the target slug, and to build the fork head ref. Return an exit-2 message when no remote matches, or when the derived base differs from the recorded one.

2. [attention · 3] **`.agent/tools/task/task_ship.py:15`** — the presence of an `upstream` remote decides the PR target
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
```
Any worktree with a stray `upstream` remote sends the PR there, even when the task's repo is `origin`. The fork-owner prefix on the head ref then comes from `origin`, so the PR is created in a repo the task never named.

Fix: Select the remote by matching its URL slug against the recorded `repo_remote_url`. Treat the fork case as: origin is the fork and the recorded repo is reachable as `upstream`.