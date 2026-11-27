Assessment: request-changes — the change copies the commit and PR logic into a prose recipe in `crew-implement` instead of putting it in `crew-task.py`, and it has ordering and recovery defects.
Read beyond the package: none (a Glob for `*crew*` and a Grep for `crew commit`, `mark-done` and `crew-commit` found only this SKILL.md; `crew-task.py` and the `crew-commit`/`open-pr` skills are not in the working directory).

Approach: redirect — add a `crew-task.py ship` subcommand that owns the sequence and its state, and have the skill call it, instead of a bash recipe the orchestrator re-types.
Alternatives considered:
- Don't build it: keep `crew commit` and `crew open pr` and make `crew-implement` hand off to them. This loses on friction (three skills), but it keeps one owner for commit and PR rules. It beats the chosen design because the chosen one duplicates those skills' logic.
- Have `crew-implement` invoke the existing `crew commit` and `crew open pr` skills in sequence. This is the smallest change and leaves one owner for commit and PR conventions. It is better than the inline recipe, and a `ship` subcommand is better still.
- `crew-task.py ship <task-dir>` is deterministic and testable. It resumes from recorded state and gates `mark-done` on a pushed branch. This is the recommended design.

Next changes and their cost:
- Changing commit or PR conventions (title format, body template, attribution) now means editing this skill and the older skills, which are still there. Two owners.
- Adding a second test command, or a repo that has no `evals/test.sh`, means editing the prose recipe.
- Resuming after a partial failure currently needs the orchestrator to reason from git state.

1. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:20`** — the shipping sequence has a second owner and `mark-done` sits outside the CLI that owns task state
```
PR_URL=$(GH_PAGER=cat gh pr create --draft ...) && echo "$PR_URL"
~/.agent/bin/crew-task.py mark-done "$TASK_DIR" --pr-url "$PR_URL"
```
The commit, PR and merge rules now live both here and in `crew commit` and `crew open pr`. Those skills are still the way to ship an unreviewed task by hand. When one changes, they disagree, for example on the title format or on whether the PR body is checked. Fix: add `crew-task.py ship`, which runs the steps in order and records progress in `.task-id`/PROGRESS.md. Have the skill call it and retire or delegate the old skills.

2. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:15`** — the merge and tests run after the commit, and the retry advice leaves the sequence in an unsafe state
```
git commit -m "$TITLE" ...
git fetch origin "$BASE" && git merge --no-edit "origin/$BASE"
bash evals/test.sh -n auto
```
If the merge conflicts, the merge stops mid-way and the orchestrator must resolve it. If the tests fail after the merge, the fix commit follows a merge commit. The instruction "run the remaining steps again" would then re-run `git commit` with nothing to commit, which fails and stops the sequence. Likewise `mark-done` can fail after the PR is created, and a re-run then fails at `gh pr create` because the PR already exists. Fix: make each step idempotent or state-aware, which is easier inside a CLI. At minimum say which steps to skip on re-entry.

3. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:6`** — the recipe uses variables that nothing defines, and the ship step has no review gate
```
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
... --body-file "$BODY_FILE"
```
`$TITLE`, `$ATTRIBUTION`, `$BODY_FILE` and `$TASK_DIR` are never set in this skill. The `evals/test.sh -n auto` line is hard-coded even though the comment says the tests come from the spec's `## Tests` section. An orchestrator can therefore commit with an empty title, or run the wrong tests in a repo that lacks that script. The old text said to run `crew review` before commit, and the new text demotes it to "if the change has not been reviewed". That puts unreviewed code on a pushed PR after a single "go". Fix: have the CLI derive the title, the body and the test commands from SPEC.md. Make review status a gate that `ship` checks, not a note.

4. [nit · 3] **`.cursor/skills/crew-implement/SKILL.md:12`** — `git add -A` stages anything in the worktree
```
git add -A
```
Stray files such as logs and `.task-id` itself, if it is not ignored, go into the commit. Fix: stage the paths the spec lists, or check `git status` before staging.