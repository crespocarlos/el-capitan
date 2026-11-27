Assessment: request-changes — the Ship step copies the `crew commit` and `crew open pr` logic into a third skill instead of reusing those skills. It also moves the task-state gate from the CLI into prose.
Read beyond the package: grep for `mark-done`, `crew commit`, `crew open pr` and `.task-id` found only this file. The old skills, `crew-task.py` and the tests are not in the working directory.

Approach: redirect — Keep `crew commit` and `crew open pr` as the owners of their steps. Have `crew-implement` hand off to them, or call a single `crew-task.py ship` command, instead of re-implementing the chain as inline bash.
Alternatives considered:
- Don't build it: keep the three skills and have Step 7 say "run commit, then open pr" in one handoff. This leaves the owner typing two commands, and that is the only need it leaves unmet. It keeps one owner per step and costs almost nothing.
- Have Step 7 invoke the existing `crew commit` and `crew open pr` skills in sequence. The owner gets one flow, and the commit and PR rules stay in one place. This beats the inline copy.
- Add a `crew-task.py ship` subcommand that takes the worktree and base from `.task-id`, so the CLI owns the sequence and its gates. This is testable and works in any harness. It costs more to build than the first two but is the most robust option.
- Inline bash in the skill, as chosen. It is the cheapest to write but forks the commit and PR logic, and a shell snippet in prose cannot be tested.

1. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:14`** — Ship step duplicates `crew commit` and `crew open pr` and leaves them with a second owner
```
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
...
PR_URL=$(GH_PAGER=cat gh pr create --draft ...
```
The commit and PR rules now live in two places: the existing skills and this snippet. The snippet defines none of `$TITLE`, `$ATTRIBUTION`, `$BODY_FILE` or `$TASK_DIR`. Suppose `crew commit` later changes its message format, adds a secrets check or changes the staging rules. Ship will not pick up the change, so the same task commits differently depending on which route the owner took. The old skills still exist and nothing says which one is canonical. I could only see this one file, so I could not read their current rules. The one consumer I found is this file.
Fix: Have Step 7 delegate to the `crew commit` and `crew open pr` skills, or move the sequence into a `crew-task.py ship` subcommand. Do not paste the commands inline.

2. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:12`** — `git add -A` stages everything in the worktree
```
cd "$(jq -r .worktree "$TASK_DIR/.task-id")"
git add -A
```
`git add -A` stages anything untracked in the worktree: scratch files, `.env` files and the task's own `.task-id` or PROGRESS.md if they sit inside it. Say a build artifact or a local credentials file is untracked. It lands in a commit and is then pushed to the remote. The old `crew commit` may have scoped what it staged. I could not verify that.
Fix: Stage an explicit list of paths from the spec, or reuse whatever scoping `crew commit` applies.

3. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:23`** — the recovery instruction repeats side-effecting steps, and the tests are hardcoded
```
If a step fails, fix the cause, commit the fix, and run the remaining steps again.
bash evals/test.sh -n auto        # the spec's `## Tests` commands
```
Suppose the tests fail after the merge. The owner fixes the cause, commits, then "runs the remaining steps", which are ambiguous and include the second `git commit` and `git merge`. If `gh pr create` fails after the push, a rerun of the whole block fails on the existing branch or creates a duplicate PR. Then `mark-done` never runs, so the task stays open even though the PR exists. The test line hardcodes `evals/test.sh` and only comments that it stands for the spec's tests, so a spec with different test commands gets the wrong ones. There is also a `mark-done` hole: if `gh pr create` fails, `$PR_URL` is empty, and the `&& echo` guard covers only the assignment line. The skill does not say that this failure stops the chain, so `mark-done` could run with an empty URL.
Fix: Make Ship idempotent and resumable, with a per-step check such as "PR already exists for this branch", or move it into `crew-task.py` so it can track which step it reached. Read the test commands from the spec instead of hardcoding them.

4. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:21`** — `mark-done` is called with a hardcoded path and no gate on review
```
~/.agent/bin/crew-task.py mark-done "$TASK_DIR" --pr-url "$PR_URL"
> Next: run `crew review` first if the change has not been reviewed.
```
`crew-task.py` owns the task gates, but this change makes the review gate advisory. The old handoff put `crew review` before the commit, and the new text says to run it "if the change has not been reviewed". An owner who says "go" gets an unreviewed push and a draft PR marked done, because the skill does not check for review. The `~/.agent/bin` path also assumes one install layout, and `jq` is assumed to be present. I did not find the CLI's own checks, so this depends on whether `mark-done` enforces the review gate.
Fix: Have `mark-done`, or a `ship` subcommand, refuse to run until review is recorded, and put review before Ship in the step order.