Assessment: request-changes — the Ship step copies the `crew commit` and `crew open pr` logic into a second place, and it leaves out the gates and ordering that those skills presumably enforce.

Read beyond the package: grep for `mark-done`, `crew commit`, `crew open pr` and `.task-id`, and a glob for `*crew*`. The only hit is the changed SKILL.md. The `crew-commit` and `crew-open-pr` skills and `crew-task.py` are not in the working directory, so I could not read what they enforce.

Approach: redirect — Keep `crew commit` and `crew open pr` as the owners of shipping. Have `crew-implement` hand off to them, or call one `crew-task.py ship` subcommand. Don't re-inline the pipeline as shell in a skill.
Alternatives considered:
- Don't build it; keep the three skills and make the handoff line say so — this has the lowest cost and no duplicated logic. It loses on owner friction, which is the problem the change set out to fix.
- `crew-implement` invokes the existing `crew-commit` and `crew-open-pr` skills in sequence after the owner's go — this removes the manual steps and leaves one owner for each rule, so it beats the inline script.
- A `crew-task.py ship` subcommand that owns the worktree, commit, merge, test, push, PR and `mark-done` sequence, with `crew-implement` calling it — this is testable and resumable, and it keeps the state transitions inside the CLI that owns the state. It is the best design, but it costs the most to build.
- The chosen inline bash in the skill — this is the cheapest to write but has the problems below.

Next changes and what each costs under this design:
- A new commit-message or PR-body rule would have to be edited in `crew-commit`, `crew-open-pr` and this block.
- A new gate before push, such as a review-passed check, would need the same edit in all three places.
- A different base or test command per repo means every skill carrying a copy has to change.

1. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:21`** — `mark-done` is called after an unreviewed ship, and the review gate is dropped
```
~/.agent/bin/crew-task.py mark-done "$TASK_DIR" --pr-url "$PR_URL"
> Next: run `crew review` first if the change has not been reviewed.
```
The old flow had review come before commit and PR. Now a task whose tests pass and whose owner says go is committed, pushed and marked done, and review is only suggested afterwards. The task state then says done for code that was never reviewed, and the push has already happened. `mark-done` is the gate in the task CLI, and this skill now calls it unconditionally.
Fix: Require a recorded review pass (or have `crew-task.py` enforce it) before the Ship step runs. Have `crew-task.py` do the ship transition so its gates apply.

2. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:13-21`** — Facts with two owners: the ship logic duplicates `crew commit` and `crew open pr`
```
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
...
gh pr create --draft --title "$TITLE" --body-file "$BODY_FILE" --base "$BASE"
```
The old skills presumably own staging rules, message format, the PR template and base detection. This block is a second copy. If `crew commit` excludes certain files or checks the branch, this copy won't, and the two will drift apart. `git add -A` stages anything in the worktree, including scratch files and `.task-id` if it is not ignored. `$TITLE`, `$ATTRIBUTION`, `$BODY_FILE` and `$TASK_DIR` are never defined in the step.
Fix: Delegate to the owning skills or to one CLI subcommand. If the block stays, define every variable and stage explicit paths.

3. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:15-19`** — Wrong order and an unsafe retry path
```
git commit ...
git fetch origin "$BASE" && git merge --no-edit "origin/$BASE"
bash evals/test.sh -n auto
git push -u origin HEAD
```
A commit is made before the merge and tests, so a failure leaves a local commit. The recovery text says "commit the fix, and run the remaining steps again". Re-running from the top fails on `git commit` with nothing to commit, which is not the same as stopping at the first failure. Stopping at the first failure is also not enforced, because these are separate lines with no `set -e`. A failed `git commit` or merge conflict would carry on to the tests and the push. The `gh pr create` step could also fail after the push, and a retry would then try to create the PR again. Re-running tests after the merge is the right idea.
Fix: Make the sequence one script with `set -euo pipefail` and idempotent steps (skip a commit with nothing staged, reuse an existing PR). Better, put it in the CLI.

4. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:18`** — The spec's tests are hard-coded, and the hook breaks the "one harness" assumption
```
bash evals/test.sh -n auto        # the spec's `## Tests` commands
```
The comment says the spec's tests are run, but the command is a literal repo-specific path. A task whose spec lists different tests ships after running the wrong suite. The `~/.agent/bin/` path and the `.cursor/skills` location are also tied to one harness. A different harness or machine has no `crew-task.py` at that path.
Fix: Read the commands from the spec's `## Tests` section, or let `crew-task.py` do it. Resolve the CLI by name rather than by a home-directory path.

5. [needs more info · 2] **`.cursor/skills/crew-implement/SKILL.md:12`** — Does `.task-id` record `.worktree` and `.base` as JSON?
The step reads `jq -r .worktree` and `jq -r .base` from `.task-id`. If the file is a plain ID, or uses different keys, `cd` goes to an empty path and `BASE` is `null`. Then the merge targets `origin/null`. If `crew-task.py` writes a different format, what breaks is the whole Ship step. Please confirm the schema in `crew-task.py`.