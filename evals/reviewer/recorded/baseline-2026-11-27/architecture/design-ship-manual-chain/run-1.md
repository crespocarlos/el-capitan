Assessment: request-changes — the Ship step puts the whole commit/push/PR/mark-done sequence in prose that the orchestrator improvises, instead of in `crew-task.py`, which owns the task state and gates. It also drops the review gate.

1. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:8`** — Review gate removed, and ship now pushes unreviewed work
```
After every task passes and the owner says go, commit and open the draft PR
...
> Next: run `crew review` first if the change has not been reviewed.
```
The old contract was "Stop after all tasks pass. Never commit, push, or create a PR", with `crew review` ordered before `crew commit`. The new text makes review optional ("if the change has not been reviewed"). Nothing in the Ship step checks whether a review happened, so the owner's "go" can push unreviewed code. `crew-task.py` owns the gates and is the natural place to enforce this. The Ship step doesn't call it before pushing. It is only called at the end, for `mark-done`. Fix: add a `crew-task.py` gate, for example `ship-check`, that fails unless a review is recorded. Call it first in the Ship step. Alternatively, keep `crew review` as a mandatory step before Ship.

2. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:15`** — `git add -A` and a bare `git commit` can ship stray files and fail on empty changes
```
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
```
`git add -A` in the worktree also stages anything untracked there, such as `.task-id`, PROGRESS.md, scratch files and secrets. `crew commit` presumably had a scoped staging policy. Here that policy is gone. Fix: stage only the paths the spec lists, or use an exclusion list owned by `crew-task.py`. Also guard the commit so a no-change case doesn't abort the chain.

3. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:22`** — Retry instruction is not idempotent and can leave the task state inconsistent
```
If a step fails, fix the cause, commit the fix, and run the remaining steps again.
```
The chain has external side effects: push, `gh pr create` and `mark-done`. "Run the remaining steps" is undefined when the failure happens after the push but before `mark-done`. A second `gh pr create` then fails or duplicates the PR. The recorded task state can also disagree with the real state: a PR exists but the task isn't marked done. If the merge produces conflicts, the instruction "fix the cause, commit" is unclear. Fix: move the sequence into a `crew-task.py ship` subcommand that records progress in PROGRESS.md and resumes idempotently. It should check for an existing PR before creating one.

4. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:17`** — Tests are hardcoded and the merge runs unconditionally
```
bash evals/test.sh -n auto        # the spec's `## Tests` commands
```
The comment says these are the spec's commands, but the line hardcodes one repo-specific script. Any other task will either run the wrong tests or skip its own. Meanwhile `$TITLE`, `$ATTRIBUTION`, `$BODY_FILE` and `$TASK_DIR` are never defined in the step, so the contract on those inputs is implicit. If `jq` returns null for `.worktree`, `cd` fails and everything after it runs in the wrong directory. Fix: read the test commands from the SPEC. Run the block under `set -euo pipefail`. Define and validate the variables. Better, have `crew-task.py` supply them.

5. [needs more info · 3] **`.cursor/skills/crew-implement/SKILL.md:7`** — Are `crew commit` and `crew open pr` retired or left as parallel paths?
The text says "the owner no longer runs `crew commit` and `crew open pr` by hand", but the diff doesn't touch those skills. If they remain, two implementations of commit and PR logic will drift apart. Which one is canonical? If the old skills are meant to be deleted, any other consumer that references them in its handoff text will point at skills that no longer exist.