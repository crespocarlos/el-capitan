Assessment: request-changes — the Ship step moves commit, push and PR creation into `crew-implement` and drops the review gate, so the old review → commit → PR order is no longer enforced anywhere.

I could only read `SKILL.md`. The package has no `crew-task.py`, `crew-commit` or `crew-open-pr`, so the checks below rest on the diff alone. I could not count consumers of the old skills or of the `.task-id` fields.

1. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:27`** — Review is no longer a precondition for push and PR creation
```
> Next: run `crew review` first if the change has not been reviewed.
```
The old Step 7 said "Stop after all tasks pass. Never commit, push, or create a PR" and sent the owner to `crew review`. The new step ships immediately "after the owner's go". The review is now advisory text that appears after the PR is already open. `mark-done` is described as a gate in `crew-task.py`, but nothing here shows it checking for a review. This skips a quality gate and moves the review step, which the task CLI owns, into prose.
Fix: Put the review before Ship, either as a numbered step that must pass or as a check in `crew-task.py` that `mark-done` (or a new `ship` subcommand) requires a recorded review. Change the trailing "Next:" line so it no longer says to review after the PR exists.

2. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:12-21`** — Ship logic is duplicated in an orchestrator-run shell block instead of the task CLI
```
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
...
~/.agent/bin/crew-task.py mark-done "$TASK_DIR" --pr-url "$PR_URL"
```
`crew-task.py` owns task state, and this block reads its `.task-id` file directly with `jq` (`.worktree`, `.base`). That bypasses the CLI and makes the file's schema an implicit contract with this skill. The commit, merge, test and PR logic previously lived in `crew-commit` and `crew-open-pr`. It is now copied into a skill document that any orchestrator interprets differently. `$TITLE`, `$ATTRIBUTION`, `$BODY_FILE` and `$TASK_DIR` are never defined in the block. The skills `crew-commit` and `crew-open-pr` are not shown, so I could not check whether they are removed or kept and now drift from this block.
Fix: Add a `crew-task.py ship` subcommand that reads the worktree and base itself and runs these steps. Have the skill call that one command. Delete or redirect the old skills so there is one implementation.

3. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:13-15`** — `git add -A` after `cd` into a worktree with no guard
```
cd "$(jq -r .worktree "$TASK_DIR/.task-id")"
...
git add -A
```
If `.task-id` lacks `.worktree` or `.base`, `jq -r` prints `null` and `cd null` fails. The block has no `set -e`, and "stop at the first failure" is only prose. A failed `cd` would leave `git add -A` and `git commit` running in the orchestrator's current directory. `git add -A` also stages untracked scratch files, such as PROGRESS.md and `.task-id`, if they sit inside the worktree.
Fix: Run the block under `set -euo pipefail`, assert that the worktree path exists and that `git rev-parse --show-toplevel` matches it, and stage only the paths the spec lists.

4. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:15-17`** — Failure recovery re-runs a sequence that is not idempotent
```
git fetch origin "$BASE" && git merge --no-edit "origin/$BASE"
bash evals/test.sh -n auto
```
"Fix the cause, commit the fix, and run the remaining steps again" leaves the state ambiguous after a merge conflict or a failed push. A failure at `gh pr create` after the push can leave a pushed branch with no PR, or a retry that opens a second PR. The test command is also hard-coded to `evals/test.sh` while the comment says it is the spec's `## Tests` commands, so it will be wrong for any task whose spec lists other tests.
Fix: Make the steps resumable by checking whether a PR already exists for the branch (`gh pr view`) before creating one. Read the test commands from SPEC.md instead of hard-coding them.

5. [needs more info · 2] **`.cursor/skills/crew-implement/SKILL.md:6`** — Does `mark-done` refuse tasks without a recorded review, or reject a `--pr-url` it didn't create?
The change tells the orchestrator to call `mark-done` with a new `--pr-url` argument. If `crew-task.py` does not already accept that flag, or does not check review status, the last step fails after the PR is open. Then the task is shipped but not marked done, or it is marked done without having been reviewed. Please confirm the `mark-done` contract.