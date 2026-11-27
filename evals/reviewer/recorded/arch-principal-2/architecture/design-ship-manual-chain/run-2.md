Assessment: request-changes — the change copies the commit and PR skills into `crew-implement` as inline bash, so there are now two copies of the ship logic. The ship step also drops safeguards that those skills presumably enforced.

Read beyond the package: none. The directory holds only `SKILL.md`, and `crew-commit`, `crew-open-pr` and `crew-task.py` are not in it. The claims below about those files are inferences from the diff, not things I read.

Approach: redirect — Ship should call one deterministic `crew-task.py ship` subcommand, or reuse the existing commit and PR skills, instead of inlining a bash chain in a skill prompt.
Alternatives considered:
- Keep the three skills and only chain them (Step 7 invokes `crew commit` then `crew open pr`) — this wins on reuse and leaves one owner for commit and PR logic. It is a smaller change, but it keeps three owner handoffs if the goal is fewer manual steps.
- Add `crew-task.py ship` that reads `.task-id`, commits, merges the base, runs the spec's tests, pushes, opens the PR and marks done — it wins because the CLI already owns the task state and gates. It is testable and behaves the same under every harness, and it can resume after a failure. It costs a new subcommand.
- Inline bash in the skill (chosen) — it is cheap now, but the logic is unowned and untestable, and it can drift from the commit and PR skills.
- Do nothing — this leaves the manual three-step chain, which is the pain the change set out to remove.

1. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:15`** — `git add -A` and a blind commit replace the commit skill's safeguards
```
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
```
The `crew commit` skill presumably chose files and checked for secrets, and the removed text said "Never commit, push, or create a PR". A worktree holding stray files (`.env`, logs, scratch output, `.task-id` or PROGRESS.md if they are untracked there) gets committed and pushed to a public PR. `$TITLE` and `$ATTRIBUTION` are never defined, so the commit message can be empty.
Fix: move the staging, message and attribution logic into one owner (`crew-task.py ship`, or the existing commit skill), and stage an explicit file list or respect an allowlist.

2. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:16`** — the commit and merge are not safe to retry or to run unattended
```
git fetch origin "$BASE" && git merge --no-edit "origin/$BASE"
...
If a step fails, fix the cause, commit the fix, and run the remaining steps again.
```
A merge conflict leaves the repo mid-merge, and "commit the fix, rerun the remaining steps" is ambiguous about which steps remain. A rerun after a conflict can repeat `git commit` and fail on an empty commit. A rerun after a push or PR failure can create a duplicate PR. `mark-done` runs only if `gh pr create` succeeded, so a `gh` failure leaves the task not done even though the branch was pushed.
Fix: make ship idempotent and resumable. It should check for an existing PR (`gh pr view`), skip the commit when the tree is clean, and record the stage reached in PROGRESS.md.

3. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:17`** — the test command is hardcoded, so the spec's `## Tests` section has two owners
```
bash evals/test.sh -n auto        # the spec's `## Tests` commands
```
The comment says the commands come from the spec, but the line hardcodes one repo's script. A task whose spec lists different tests runs the wrong command and is marked done anyway. The unchanged `crew-implement` skill (which the diff does not show) is the owner of the "Verify:" and test contract.
Fix: have the ship step read the spec's `## Tests` commands, or have the CLI do so, and don't hardcode `evals/test.sh`.

4. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:6`** — the review step is no longer in the chain
```
> Next: run `crew review` first if the change has not been reviewed.
```
The old handoff ran review, then commit, then PR. Ship now runs after "the owner says go", and nothing in the chain enforces a review. An unreviewed change is pushed and opened as a PR, and `mark-done` records the task as finished.
Fix: put a review gate in `crew-task.py ship` or `mark-done` (a review-done marker in PROGRESS.md), and don't leave it as an advisory note.

5. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:13`** — the chain assumes a bash, jq, gh and `~/.agent` install
```
cd "$(jq -r .worktree "$TASK_DIR/.task-id")"
~/.agent/bin/crew-task.py mark-done ...
```
The file lives under `.cursor/skills`, so other harnesses probably run it too. The chain hardcodes `~/.agent/bin` and needs `jq` and `gh`, and `$TASK_DIR`, `$BODY_FILE`, `$TITLE` and `$ATTRIBUTION` are unset in the snippet. On a machine without these, the `cd` fails; if the model improvises around that, the later `git` commands run in the wrong repository.
Fix: do the lookup inside `crew-task.py`, which already reads `.task-id`, and have the skill invoke it with `set -e` semantics.