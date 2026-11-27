I could only read SPEC.md. The case directory has no source files, so I couldn't check any task path.

**Critical**

**Task 1 / Task 3** — `slug_from_url` is used before any task creates it.
Task 1 calls `slug_from_url`, but Task 3 is the task that adds it to `.agent/tools/lib/git.py`. Task 1's verify (`-k record_pr`) would fail with an ImportError or NameError. Nothing in Task 1 imports the helper either.

Fix: move Task 3 to the first position and have Task 1 say to import it (`from lib.git import slug_from_url`, or whatever the existing import convention is).

**Task 2** — Task 2 has no verify line, and the tests it adds are ones the other tasks depend on.
The builder has nothing to run after Task 2. `-k record_pr` in Task 1's verify only selects tests whose names contain `record_pr`, and the spec doesn't say what to name the new ssh/https/`.git`/case rows. The new tests may never be selected, or Task 1's verify may pass without covering them.

Fix: give Task 2 a verify line, such as `bash evals/test.sh evals/tools/test_lifecycle.py -k record_pr`. Specify the test names so that `-k` selects them. Order the tasks helper, then tests, then the `tasks_in` change, so the tests fail before the fix and pass after it.

**Important**

**Task 3** — The helper's behaviour for non-matching input is unspecified, and nothing tests the failure case.
The signature is `-> str | None`, but the spec doesn't say when it returns `None`. It also doesn't say how `tasks_in` handles `None`. A task with an empty or missing `repo_remote_url` could raise a KeyError. Two `None` values could also compare equal and match unrelated tasks to a PR.

Fix: state the `None` cases and the `tasks_in` handling (skip the task), and add a test row for them in Task 2.

**Acceptance criteria** — The criteria name no proving command.
"`.git` suffixes and letter case do not matter" has no inspection path or command. The first criterion is also only covered if Task 2's rows exist and get selected.

Fix: tie each criterion to a named test, or add "run `bash evals/test.sh evals/tools/test_lifecycle.py`".

**Tests** — The `## Tests` section only has `### Unit`.
`record-pr` is a tool that other scripts call, probably through a CLI or the harness. I couldn't verify that, so I don't know whether the unit layer crosses the boundary.

Fix: confirm whether `tasks_in` is reached through a CLI entry point, and add an integration layer if it is.

Verdict: 4 finding(s), 3 unverified: `.agent/tools/task/task_record_pr.py`, `.agent/tools/lib/git.py`, `evals/tools/test_lifecycle.py` (none exist in the case directory)