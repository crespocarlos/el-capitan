Assessment: request-changes — `ship` re-derives repo, base and remote from git and the spec text, even though Gate 2 already recorded `repo_remote_url` and `base` in `.task-id`.
Read beyond the package: none (the only other file in the directory is `.task-id`)

Approach: redirect — read the target repo and base from the Gate 2 record and verify them against git. Don't guess them again at ship time.
Alternatives considered:
- Use the recorded `repo_remote_url` and `base`, and refuse on mismatch — wins. Gate 2 exists to pin them, and `ship` already checks the branch against the record the same way.
- Keep the re-derivation and use the record only as a fallback — loses. The two owners then disagree silently, and the fallback is only reached when git is already broken.
- Don't build `ship`; leave the steps manual — loses. It leaves the one-step goal unmet, but the goal is fine and only the source of the target is wrong.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:11`** — target repo and base re-derived instead of read from the Gate 2 record
```
remote = "upstream" if remote_url(tree, "upstream") else "origin"
named = SPEC_BASE.search(task.text)
base = named.group(1) if named else default_branch(tree, remote)
target = slug_from_url(remote_url(tree, remote)) or (task.repo if remote == "origin" else "")
```
`.task-id` records `repo_remote_url` (`acme/widgets`) and `base` (`main`), but `where_to` never reads either one. A worktree that has an `upstream` remote, for example one added for an unrelated fork, makes `ship` open the PR against that remote's repo, not the task's. If the spec's `## Base:` line was edited after Gate 2, or is missing and the remote's default branch is not `main`, the PR targets a different base than the one recorded. `prepare` checks the branch against the record but not the repo, so the push and PR go to the wrong place without any error. This is a fact with two owners: Gate 2's record and the git/spec re-derivation.
Fix: take `target` from `slug_from_url(task.meta["repo_remote_url"])` and `base` from `task.meta["base"]`. Pick the remote whose URL slug matches the recorded repo, or the fork's `upstream`, and raise `Stop` when none matches. Use a spec or git value only to cross-check.

2. [attention · 3] **`.agent/tools/task/task_ship.py:21`** — the tool derives the fork head owner from `origin`, not from the record
```
owner = (slug_from_url(remote_url(tree, "origin")) or "").split("/")[0]
return remote, base, target, f"{owner}:{branch}" if owner else branch
```
If `origin` cannot be parsed, `owner` is empty and the head silently falls back to the bare `branch`. The PR then looks for the branch in the upstream repo, so it fails or picks up a same-named branch there. A fork flow needs the owner, so an empty owner should stop the run.
Fix: raise `Stop` when `remote != "origin"` and `owner` is empty.