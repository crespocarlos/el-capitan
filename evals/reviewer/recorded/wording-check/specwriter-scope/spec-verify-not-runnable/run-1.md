**Task 3** — "Verify: run `crew-task.py open-pr` on a scratch task in this repository, confirm the draft PR appears on github.com, then close it by hand" cannot run.

The builder has no network, no `gh` credentials and no human to close the PR. Any check it makes would either stall or open a real PR on the repository.

Fix: delete Task 3. Cover the push and PR calls in `## Tests` with `gh` and `git` stubbed, and move the github.com check to a human-only acceptance note that says so.

**Tasks 1 and 2 / `## Tests` → Unit** — The only automated layer is Unit, but the change shells out to `git push` and `gh`.

If the tests don't stub those calls, they need the network and credentials. If they do stub them, nothing shows that the CLI wiring, the argument order or the failure handling works. A wrong `gh pr create` flag set, such as a missing `--draft` or `--base`, would pass.

Fix: add an `### Integration` subsection. It runs `crew-task.py open-pr` as a subprocess against a temp task directory, with fake `git` and `gh` executables first on `PATH` that record their argv. Assert `--draft` and `--base` in that argv.

**Task 1** — Overloaded and loosely specified: a new module, a change to `crew-task.py`, and several unnamed behaviours.

Those behaviours are the push, the PR creation, finding the base branch, recording the URL, and detecting an existing open PR. The spec doesn't say where "the task's PR list" lives or what the file format is. Nor does it say how "open" is determined, or how the base branch is chosen. The builder has to guess, and a wrong guess fails the Task 2 rows. Task 1 also has no verify line.

Fix: split Task 1 into the module (with the PR-list storage path and format named) and the `crew-task.py` wiring. Give each task a verify line. Name the existing subcommand file to copy as the pattern.

**Tasks 1 and 2** — The order is wrong for the builder's loop. Task 1 has no verify line, and Task 2 supplies the tests that exercise Task 1. The test runner `evals/test.sh` and the row format are unnamed.

Fix: give Task 1 a verify line, for example `crew-task.py open-pr --help` exiting 0. Name an existing test file in `evals/tools/` as the pattern for Task 2.

**Acceptance criteria** — The bullets have no inspection path, and the re-run bullet is ambiguous.

"Re-running … on a task whose PR is open" doesn't say whether a closed or merged PR counts as open. Nor does it say what happens when the push fails. The first two bullets name no command or file that proves them.

Fix: tie each bullet to a named test row or an inspection of a named file. State the closed-PR and push-failure behaviour, or put them under `## Open questions`.

**Unverified:** I searched for `crew-task.py`, `evals/test.sh`, `.agent/tools/task/` and test files. The Glob returned nothing, so none of these paths could be confirmed. The path claims in Tasks 1 and 2 and in `## Tests` are unverified.

Verdict: 5 finding(s), 4 unverified