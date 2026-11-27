Assessment: request-changes — the Ship step moves commit, push, PR creation and the `mark-done` gate into an inline shell recipe in a skill, so the task CLI that owns task state no longer enforces the sequence.

1. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:21`** — `mark-done` is the last line of an unguarded script, so the task CLI's gate is bypassed by the recipe's own ordering
```bash
PR_URL=$(GH_PAGER=cat gh pr create ...) && echo "$PR_URL"
~/.agent/bin/crew-task.py mark-done "$TASK_DIR" --pr-url "$PR_URL"
```
`crew-task.py` owns task state and gates such as `mark-done`, but the ordering of commit, merge, test, push and PR now lives in prose that an LLM orchestrator interprets. The block has no `set -e`, and the "stop at the first failure" rule is only a sentence. If `gh pr create` fails, the `&&` guards only the `echo`. `PR_URL` is then empty and the next line still runs `mark-done` with an empty `--pr-url`. That records a task as done with no PR. In a separate case, a failed test run does not stop the push, because nothing enforces the stop. The state owner should enforce the preconditions.
Fix: Add a `crew-task.py ship <task-dir>` subcommand, or have `mark-done` verify a clean tree, a pushed HEAD and a non-empty `--pr-url`. The skill then calls that one command. At minimum, make the recipe `set -euo pipefail` and require `PR_URL` to be non-empty.

2. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:16`** — `git add -A` and an unreviewed commit in the worktree remove the review gate
```bash
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
```
The old flow had `crew commit` as a separate skill, which presumably handled staging scope and message conventions. I could not read that skill here, so this is unverified. `add -A` sweeps in untracked scratch files, such as `.task-id` and PROGRESS.md if they sit inside the worktree. The new "Next" line also makes review optional: "run `crew review` first if the change has not been reviewed". The old handoff placed review before commit and PR. A draft PR is the weaker risk, but the commit and push come before any review.
Fix: Stage explicit paths, or confirm that task state files are gitignored. Require a review-passed marker in the task state before Ship runs.

3. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:18`** — the spec's `## Tests` commands are hardcoded to `bash evals/test.sh -n auto`
```bash
bash evals/test.sh -n auto        # the spec's `## Tests` commands
```
The comment says the line stands for the spec's tests, but the literal command is repo-specific. An orchestrator that copies the block verbatim runs the wrong suite for any other repo or spec. That makes the post-merge re-test a silent false pass or a spurious failure.
Fix: Reference the spec's `## Tests` section explicitly, for example "run each command listed there", and drop the literal command from the block.

4. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:24`** — the retry instruction is unsafe after a partial run
```
If a step fails, fix the cause, commit the fix, and run the remaining steps again.
```
After a failed merge, the worktree is left in a conflicted state, and "commit the fix" is ambiguous. After a push that succeeded, followed by a `gh` failure, "remaining steps" is not defined, and re-running `git commit` from the top would fail on an empty commit. The recipe has no idempotency story, and it uses undefined variables (`TITLE`, `ATTRIBUTION`, `BODY_FILE`, `TASK_DIR`) with no stated source.
Fix: Define where those variables come from. Make each step resumable by checking the state, for example "if a PR already exists for HEAD, skip to `mark-done`". Moving the sequence into the CLI would solve this too.

5. [nit · 3] **`.cursor/skills/crew-implement/SKILL.md:6`** — the old `crew commit` and `crew open pr` skills are not shown as removed or deprecated
The diff only changes `crew-implement`, and the description says the three skills are replaced. I found no other crew files in the working directory, so I could not check whether the other two skills still exist. If they do, two paths now ship a task with diverging behavior.
Fix: Remove or redirect the old skills in the same change, or state that they remain as the manual path.