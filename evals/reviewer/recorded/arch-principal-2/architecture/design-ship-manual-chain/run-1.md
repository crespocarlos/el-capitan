Assessment: request-changes — the Ship step copies the commit and PR-opening logic into `crew-implement` as inline shell, so the `crew commit` and `crew open pr` skills now have a second owner. It also drops the review gate and leaves the shell sequence unsafe.
Read beyond the package: searched the working directory for crew files and for `mark-done`, `.task-id` and `worktree`. Only the changed SKILL.md exists, so I could not read `crew-task.py`, `crew-commit` or `crew-open-pr`.

Approach: redirect — Ship should be a `crew-task.py ship` subcommand, or `crew-implement` should invoke the existing commit and open-pr skills, so there is one owner of the sequence and the gates.
Alternatives considered:
- Keep three skills and have `crew-implement` end by chaining them (invoking `crew commit` then `crew open pr`). This keeps one definition of each step. It loses only the single-prompt convenience, and that is already met by the chain.
- Add `crew-task.py ship`, which runs the sequence deterministically and enforces the gates in code. It costs a subcommand, but it can be tested and works under any harness. It beats prose that an LLM executes line by line.
- Don't build it: the owner keeps running the three skills. This leaves the manual-step cost the change targets, but the change can meet that cost without a second copy of the logic.

1. [blocking · 4] **`.cursor/skills/crew-implement/SKILL.md:Step 7`** — Review gate removed and replaced by a trailing "if not reviewed" hint
```
> Next: run `crew review` first if the change has not been reviewed.
```
The old flow made review a required step before commit. Now "owner says go" triggers commit, push and PR creation, and nothing checks that review happened. An owner who says go straight after the tasks pass pushes unreviewed code. Whatever `mark-done` gates on is reached only after the push, so it cannot stop this.
Fix: Check for review evidence before `git add` (for example a `crew-task.py` gate), or keep review as an explicit step before Ship.

2. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:Step 7`** — Fact with two owners: commit and PR logic duplicated from `crew commit` and `crew open pr`
```
git add -A
git commit -m "$TITLE" -m "Co-Authored-By: $ATTRIBUTION"
```
These skills still exist and hold their own rules for staging, message format and PR body. This block hardcodes its own versions. A rule changed in `crew commit` (for example excluding files or the trailer format) will not reach the Ship path. `git add -A` also takes untracked scratch files such as `.task-id` and PROGRESS.md that the other skills may exclude.
Fix: Delegate to those skills, or move the sequence into `crew-task.py ship`. Do not keep two copies.

3. [attention · 4] **`.cursor/skills/crew-implement/SKILL.md:Step 7`** — Hardcoded `evals/test.sh` and undefined variables
```
bash evals/test.sh -n auto        # the spec's `## Tests` commands
```
The comment says the spec's tests run, but the command is fixed to one repo's script. A task whose SPEC lists different tests passes the gate without them being run. `$TITLE`, `$ATTRIBUTION`, `$BODY_FILE` and `$TASK_DIR` are never defined, so an empty `$TITLE` makes an empty commit message.
Fix: Read the commands from SPEC `## Tests`, and have the CLI derive the title, attribution and body from the task state.

4. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:Step 7`** — Retry guidance is not idempotent
```
If a step fails, fix the cause, commit the fix, and run the remaining steps again.
```
If the merge conflicts, the tree is left mid-merge and "commit the fix" is ambiguous. If `gh pr create` fails after the push, or `mark-done` fails after the PR exists, "remaining steps" is not defined. A rerun that includes `gh pr create` opens a duplicate PR. A failed `mark-done` leaves a PR whose task is not recorded done.
Fix: Make the sequence resumable in code by checking for an existing PR (`gh pr view`) and recording the step reached in PROGRESS.md.

5. [attention · 3] **`.cursor/skills/crew-implement/SKILL.md:Step 7`** — Direct reads of `.task-id` bypass the task CLI
```
cd "$(jq -r .worktree "$TASK_DIR/.task-id")"
```
`crew-task.py` owns the `.task-id` format, but this skill parses it with `jq` using `.worktree` and `.base`. If the CLI changes those keys, or `jq` is missing, `cd` fails or reads `null`. Because the script has no `set -e`, the later `git add -A` can then run in the wrong directory.
Fix: Add a `crew-task.py` accessor or a `ship` subcommand, and stop the sequence on the first failure with `&&` or `set -e`.

6. [nit · 3] **`.cursor/skills/crew-implement/SKILL.md:Step 7`** — Hardcoded `~/.agent/bin/crew-task.py` path
The path assumes one install layout. Another harness or machine that installs elsewhere cannot run the final step, and it fails after the PR is already open. Use the resolved command name the other skills use.