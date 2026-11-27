**Critical**

**Task 3** — the verify line cannot run in the builder's environment: "run `crew-task.py open-pr` on a scratch task in this repository, confirm the draft PR appears on github.com, then close it by hand."

The builder has no network, no `gh` credentials and nobody to answer prompts. It also cannot browse github.com or close a PR by hand. Three verify runs fail and the task is marked failed. A pass would also leave a live draft PR on the real repository.

Fix: delete Task 3 and cover the real-`gh` path in `## Tests` with a stubbed `gh` and `git push`. If a live check is wanted, put it in the acceptance criteria as an explicitly human check.

**Tasks 1 and 2** — no task has a verify line, and the repository paths are unconfirmed.

Task 1 has no verify line. Task 2's only check is `## Tests`, which runs only at the end, so a broken Task 1 is first caught after the builder has moved on. The workspace contains only SPEC.md. I could not find `crew-task.py`, `.agent/tools/task/`, `evals/test.sh` or `evals/tools/`. The paths are unconfirmed, and `crew-task.py` is given without a directory. The builder cannot tell where the "task's PR list" lives or how to follow the existing subcommand pattern.

Fix: give `crew-task.py` its full repository-root path. Add a `Verify:` line to Tasks 1 and 2 (for example `bash evals/test.sh evals/tools/test_open_pr.py`). Name an existing subcommand file for the builder to copy. State where the PR list is stored.

**Important**

**Task 1** — it combines a new module, a CLI subcommand, a push, PR creation, and the update to the stored PR list in one task.

If it fails part-way, the builder cannot tell which edit broke it. The criterion "Re-running it on a task whose PR is open prints the existing URL" needs a lookup of the existing PR, and Task 1 never says how that lookup works.

Fix: split into (a) the `task_open_pr.py` logic with `gh` and `git` calls injectable, and (b) the `crew-task.py` wiring. Make the existing-PR lookup explicit in the task.

**`## Tests`** — the tests need a `gh` and `git` stub, and nothing creates one.

`### Unit` is the only layer, yet the change crosses a process boundary: the CLI calls `gh` and pushes. Without a fake `gh`, `test_open_pr.py` either hits the network or fails. Also, Task 2 only names "happy path and re-run" rows, and no criterion asks for tests of the base-branch or draft flags.

Fix: add an `### Integration` layer that runs `crew-task.py open-pr` with a stub `gh` on `PATH` and a local bare remote. Have Task 2 create that fixture.

**Acceptance criteria** — the criteria do not say how the builder proves them.

"Opens a draft PR against the base branch" and "appended to the task's PR list" name no command or file to inspect. The builder cannot mark them `[x]`.

Fix: tie each criterion to a test row or an `rg` on the recorded stub-`gh` arguments (`--draft`, `--base`).

Verdict: 4 finding(s), 4 unverified: `crew-task.py`, `.agent/tools/task/`, `evals/test.sh`, `evals/tools/`