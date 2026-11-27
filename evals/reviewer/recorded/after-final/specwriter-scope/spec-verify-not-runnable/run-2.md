**Critical**

**Task 3** — "run `crew-task.py open-pr` on a scratch task in this repository, confirm the draft PR appears on github.com, then close it by hand"

The builder has no network, no `gh` credentials and no human to answer prompts. It also can't open github.com or close a PR by hand. The check can never pass, so the builder retries three times and marks the task failed. If it did run, it would push a real branch and open a real PR. Delete Task 3 as a verify step. Cover the `gh` and `git` boundary in `## Tests` with a stubbed `gh` and `git` on PATH (`### Integration`). Put the live github.com check in the acceptance criteria as a human-only check.

**Important**

**Task 1** — "add `.agent/tools/task/task_open_pr.py` and the `open-pr` subcommand in `crew-task.py`"

Task 1 has no verify line. It touches a new module and an existing CLI at an unspecified path. `crew-task.py` is written without a directory, and Glob found only SPEC.md, so I couldn't confirm it exists. The task also leaves unstated where the "task's PR list" lives, what the base branch is, and which existing subcommand to copy. The builder would have to explore and guess. Give the full path of `crew-task.py`. Name the existing subcommand to follow. Name the file and field that hold the PR list. Add a verify line such as `crew-task.py open-pr --help` exiting 0.

**Task 2** — "add `evals/tools/test_open_pr.py` with rows for the happy path and the re-run"

The test file is created after the code it tests, and the spec doesn't say how it mocks `gh` and `git`. Without a stub, the tests need the network and fail. The "rows" wording also gives no pattern to follow, and `evals/test.sh` is unverified. Task 2 also has no verify line. Say the tests stub `gh` and `git` via PATH or a fixture. Name an existing test file as the pattern. Add the verify line `bash evals/test.sh evals/tools/test_open_pr.py`.

**Acceptance criteria** — "Re-running it on a task whose PR is open prints the existing URL and opens nothing."

This criterion has no inspection path. "PR is open" is undefined, because the spec doesn't say whether the check reads the stored list or queries `gh`. Neither criterion names a command that proves it, and no test row covers the "PR list" append. Tie each criterion to a named test case in `test_open_pr.py`. State the source of truth for "open".

**Consider**

**Tasks 1 and 2** — Task 1 adds the subcommand and there is no changelog or docs task. If `crew-task.py` usage is documented, such as a README or `--help` index, the new subcommand needs a line there. I couldn't check this because the repository has no files besides SPEC.md. The cost is stale docs. Add a docs task if a subcommand list exists.

Verdict: 5 finding(s), 3 unverified: `crew-task.py` path, `evals/test.sh`, `.agent/tools/task/` directory