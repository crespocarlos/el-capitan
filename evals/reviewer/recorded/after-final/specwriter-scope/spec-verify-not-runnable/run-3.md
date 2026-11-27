**Critical**

**Task 3** — "run `crew-task.py open-pr` on a scratch task in this repository, confirm the draft PR appears on github.com, then close it by hand."
The builder has no network, no `gh` auth, no one to act by hand and no github.com to look at, so this verify can never pass. It fails three times and the task is marked failed. It would also push a branch and open a real PR on the repository.
Fix: delete Task 3 and cover the push and PR calls in `### Unit` with a stubbed `gh` and `git`. If a real-GitHub check is wanted, list it under the criteria as a human check that needs `gh` and network.

**Task 1** — "add `.agent/tools/task/task_open_pr.py` and the `open-pr` subcommand in `crew-task.py`", with no verify line and no path for `crew-task.py`.
I searched the working directory and found only SPEC.md, so none of these paths could be verified. `crew-task.py` has no root-relative path, and the "task's PR list", "base branch" and the existing-PR lookup are not defined anywhere. The builder would guess where the PR list is stored and how an open PR is detected.
Fix: give the full path to `crew-task.py` and say which existing subcommand and PR-list field to follow. Add a verify line, for example `bash evals/test.sh evals/tools/test_open_pr.py`.

**Task 1 / Task 2** — Task 1 creates a module and edits `crew-task.py`, and Task 2 creates the tests, but only the tests run `## Tests`.
Task 1 has nothing to verify against until Task 2 exists. The `evals/tools/test_open_pr.py` path and the `evals/test.sh` runner are also unverified. The tests need a seam to stub `gh` and `git` without network. Without one, the builder may write tests that call `gh` for real and fail offline.
Fix: split Task 1 into the module and the CLI wiring. Name the stub seam and give each task a verify line that runs offline. Alternatively, put the test first so each implementation task has a check.

**Important**

**Acceptance criteria** — "Re-running it on a task whose PR is open prints the existing URL and opens nothing."
There is no check for it. Task 2's "rows for the happy path and the re-run" does not cover the "PR is open" part: a closed or merged PR, or a task with no PR yet, has no row and no stated behaviour.
Fix: add an "inspect `evals/tools/test_open_pr.py` for a re-run row that asserts the `gh pr create` stub is called zero times" check. Also say what happens when the existing PR is closed.

Verdict: 4 finding(s), 3 unverified: `crew-task.py`, `evals/test.sh`, `evals/tools/test_open_pr.py`. The working directory has no case files besides SPEC.md.