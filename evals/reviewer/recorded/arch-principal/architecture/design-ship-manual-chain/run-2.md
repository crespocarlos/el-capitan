Assessment: request-changes — the change folds commit and PR creation into `crew-implement` as inline shell. That duplicates the `crew commit` and `crew open pr` skills, whose safeguards it drops, and it leaves the task CLI's `mark-done` gate unguarded.

Read beyond the package: none (the Glob for `*crew*` returned nothing, and the Grep found only the changed SKILL.md, so `crew-task.py`, `crew-commit` and `crew-open-pr` are not in the working directory).

Approach: redirect — add one `crew-task.py ship` subcommand, or make the Ship step call the existing `crew commit` and `crew open pr` skills, instead of keeping a third copy of the shipping logic as shell in a skill prompt.
Alternatives considered:
- Keep the three skills and only add "Next" guidance — this is the cheapest option and keeps one owner per step. It loses on the stated goal of removing the owner's manual chain.
- Have Step 7 invoke the existing commit and open-pr skills — this keeps one owner for the commit rules (staging, message format, secret checks) and for the PR body. It wins on duplication. The cost is that the skills must be callable non-interactively.
- Add a `crew-task.py ship` subcommand that owns the sequence, and have the skill call it — the CLI already owns `.task-id` and the `mark-done` gate, so worktree and base lookup, ordering, retry and state transitions belong there. It is testable and idempotent. This is the best option, and I recommend it.
- Inline shell in the skill, as chosen — this is not testable and is not safely re-runnable, and it forks the rules in `crew commit` and `crew open pr`.

Next changes and their cost under this design:
- A different base branch rule, or a repo whose tests are not `evals/test.sh`, means editing prose in the skill, and then the same edit again in the commit and PR skills.
- Adding a review gate means editing three places, because nothing enforces that a review happened.
- Resuming after a half-finished ship means a hand-written recovery, because the step has no state.

1. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:21`** — `mark-done` runs with no check that review ran, and the "Next" line makes review optional
```
~/.agent/bin/crew-task.py mark-done "$TASK_DIR" --pr-url "$PR_URL"
> Next: run `crew review` first if the change has not been reviewed.
```
The old flow ended with "run `crew review`, then `crew commit`, then `crew open pr`". The new Ship step opens the PR and marks the task done, and `crew review` becomes a hint after the fact. The "owner says go" is a conversational gate and is not recorded anywhere. Nothing in the shell or the CLI checks that a review happened. A task that was never reviewed therefore reaches a draft PR and a done state. The "Next" line also reads as running after ship, so the order is contradictory. The shell has no way to read the gate state, so the guard needs a CLI command that does. I could not read `crew-task.py` to see whether `mark-done` already refuses an unreviewed task. If it does, the ordering text is still wrong.
Fix: Move the sequence into `crew-task.py ship`, and have `mark-done` refuse unless review is recorded. Alternatively, put `crew review` before Ship in the skill text and drop the trailing "Next" line.

2. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:15`** — `git add -A` and `git commit` run with no staging or secret checks
```
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
```
`git add -A` stages everything in the worktree: scratch files, `.env`, build output, and the task's own `.task-id` and PROGRESS.md if they sit inside it. These land in a pushed PR. The `crew commit` skill presumably has rules about what to stage, and this step skips them. I could not read that skill to confirm what it checks. `$TITLE`, `$ATTRIBUTION`, `$BODY_FILE` and `$TASK_DIR` are not defined in the step, so an empty `$TITLE` produces an empty-message failure or an empty PR title.
Fix: Reuse the commit skill's staging rules, for example by calling it. Stage an explicit path list, and define each variable in the step.

3. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:24`** — the retry instruction re-runs steps that are not idempotent, and `mark-done` can be skipped
```
If a step fails, fix the cause, commit the fix, and run the remaining steps again.
```
The commands are listed as one block, not as steps with state. If `gh pr create` succeeds and `mark-done` fails, a re-run of the push and PR create steps fails or opens a duplicate PR. If the merge conflicts, the worktree is left mid-merge, and "commit the fix" then runs through the `git add -A` path. `PR_URL=$(...) && echo` also sits outside any `set -e`, so a failed `gh pr create` leaves `PR_URL` empty and the next line calls `mark-done --pr-url ""`.
Fix: Make `ship` idempotent in the CLI: skip an existing PR via `gh pr view`, check `$PR_URL` is non-empty, and record the stage reached in PROGRESS.md.

4. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:18`** — the test command is a fact with two owners
```
bash evals/test.sh -n auto        # the spec's `## Tests` commands
```
The comment says the spec's `## Tests` section owns the commands, but the step hardcodes `evals/test.sh -n auto`. A task whose SPEC.md lists a different test command still runs this one and passes or fails on the wrong suite. The same wrong-suite risk applies to every repo that uses the skill. Tests also run after the merge but the fix-and-retry path re-merges, so a stale run can be pushed.
Fix: Have the CLI read the commands from the spec's `## Tests` section, or have the skill say the orchestrator substitutes them, and drop the hardcoded path.

5. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:13`** — assumes `jq`, `~/.agent/bin`, `gh` and bash everywhere
```
cd "$(jq -r .worktree "$TASK_DIR/.task-id")"
```
The orchestrator runs under several harnesses, and the shell here is zsh on macOS. If `.task-id` is not JSON, or `jq` is missing, `cd ""` goes to `$HOME`, and the later `git add -A` would stage the wrong tree. I could not read `.task-id` or the CLI to confirm its format. The `.task-id` format is also read by the CLI, so this is a second reader of that format.
Fix: Add a `crew-task.py show --field worktree` command to read it, and fail if the result is empty.