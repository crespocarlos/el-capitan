Assessment: request-changes — `ship` re-derives the target repo and base from git remotes and the spec text, even though Gate 2 already recorded `repo_remote_url` and `base` in `.task-id`.

Read beyond the package: `.task-id`

Approach: redirect — `ship` should read the target repo and base that Gate 2 recorded, and verify them against the worktree's remotes. It should not recompute them.

Alternatives considered:
- Use the recorded `repo_remote_url` and `base`, and fail if the worktree's remotes disagree. This wins. There is one owner for each fact, and a mismatch becomes an error instead of a silent retarget.
- Keep the re-derivation, as in the diff. This loses. It makes a second source of truth for the target and base, and the two can drift apart.
- Don't build `ship`; leave commit, push and PR creation to `gh pr create`. This loses on its own, because the `ship` command's checks matter: branch guard, base merge, test re-run. It would still work as a thin wrapper that takes its inputs from `.task-id`.

Next changes and what they cost:
- Fork workflows or a renamed repo: with recorded values, one field in `mark-implementing` changes. Under the diff, every command that re-derives the target changes, and each can pick a different answer.
- Other commands that need the target, such as a PR update or status check: each would copy the `upstream`/`origin` logic. A single resolver that reads `.task-id` would serve all of them.

1. [attention · 4] **`.agent/tools/task/task_ship.py:12`** — PR target is re-derived from git remotes instead of the recorded `repo_remote_url`
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
...
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
Gate 2 recorded `git@github.com:acme/widgets.git` as the task's repository. Suppose the worktree has an `upstream` remote that is a different repo, such as a personal mirror or an unrelated fork. Then the draft PR opens against that repo instead of `acme/widgets`, and nothing flags the mismatch. `task.repo` is used only as a fallback when the remote lookup returns nothing, and only for `origin`, so the recorded value never overrides the remote. This is new code, not a pre-existing problem.
Fix: resolve the target from `task.repo`. Pick the remote whose URL slug matches it, and return a `Stop` error naming both values when no remote matches. Use `upstream` only when that remote matches.

2. [attention · 4] **`.agent/tools/task/task_ship.py:13`** — Base is re-read from spec text and the remote default instead of the recorded `base`
```
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
```
`.task-id` records `"base": "main"`. If the spec's `## Base:` line is edited after Gate 2, or is absent and the remote default is something else, `ship` merges and targets a different base than the one the task was implemented against. The step that merges the base and re-runs the tests then validates against the wrong branch. The spec text and the recorded base now both claim to own the base.
Fix: use `task.meta["base"]`, and fall back to the spec and remote only for tasks written before that field existed.

3. [attention · 3] **`.agent/tools/task/task_ship.py:20`** — Head-ref owner prefix comes from `origin`'s slug without any check
```
owner = (slug_from_url(remote_url(tree, "origin")) or "").split("/")[0]
return remote, base, target, f"{owner}:{branch}" if owner else branch
```
If the owner cannot be parsed, for example from a non-GitHub URL, the code falls back to the bare `branch` without error. For a fork PR, the head then resolves against the target repository's own branches. That either fails late at PR creation or attaches to a same-named upstream branch. It would be better to stop early, as the function already does for `target`.
Fix: raise `Stop` when `remote != "origin"` and the owner cannot be derived.