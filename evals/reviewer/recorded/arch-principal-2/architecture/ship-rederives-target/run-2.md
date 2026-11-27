Assessment: request-changes — `ship` re-derives the target repo and base from git remotes and the spec, even though Gate 2 already recorded `repo_remote_url` and `base` in `.task-id`.

Read beyond the package: `.task-id`

Approach: redirect — `ship` should read the repo and base that Gate 2 recorded and verify the worktree against them. It should not derive them again from remotes and the spec text.
Alternatives considered:
- Use the recorded `repo_remote_url` and `base` as the single source, and check that the worktree's remotes agree with them. This wins. Gate 2 already wrote both values, so there is one owner, and a mismatch stops the ship instead of silently targeting another repository.
- Keep deriving the target and base from remotes and the spec, as the diff does. This loses. It creates a second owner for facts that already have one, and its result can differ from what Gate 2 recorded.
- Don't build `ship`, and keep running commit, push and `gh pr create` by hand. This loses. It leaves the target selection unchecked, and that is the step most likely to go wrong, so the one-step command is worth having.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:11`** — The PR target and base are derived again instead of read from the recorded `repo_remote_url` and `base`
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
`.task-id` records `repo_remote_url` (`git@github.com:acme/widgets.git`) and `base` (`main`), but `where_to` reads neither. If the worktree has an `upstream` remote that is a different repository (for example a stale or personal remote), the draft PR opens against that repository instead of `acme/widgets`. If the spec's `## Base:` line is edited after Gate 2, or is absent, the base comes from the remote's default branch and not from the recorded `main`. `task.repo` is only a fallback, and only when the remote is `origin`. Fork handling is a legitimate case, but it should be checked against the recorded repository, not decided by whether an `upstream` remote exists.
Fix: Take `target` from `task.meta["repo_remote_url"]` and `base` from `task.meta["base"]`. Use the `upstream`/`origin` remotes only to pick the push remote and the fork head ref. Raise `Stop` when no remote's slug matches the recorded repository.

2. [attention · 3] **`.agent/tools/task/task_ship.py:34`** — `prepare` checks the branch but not that the worktree's remotes match the task's repository
```
actual = current_branch(tree)
if not branch or actual != branch:
```
The worktree path and branch name are checked, but the worktree could belong to a different clone. A recorded path reused for another repository would pass the branch check. The commit, push and PR would then go to that other repository.
Fix: In `prepare`, check that some remote of `tree` resolves to the slug of `repo_remote_url`. Return the exit-2 message if none does.