**Task 1** — Depends on Task 3's helper, which is ordered after it.

Task 1 calls `slug_from_url`, but Task 3 is the task that adds it to `.agent/tools/lib/git.py`. The builder runs tasks in order, so Task 1's verify command fails with an ImportError or NameError. Task 2's new tests would also fail until Task 3 lands. Nothing marks the tasks as atomic, and Task 1 can't ship alone.

Fix: move the helper task first (helper, then `tasks_in`, then tests), or declare Tasks 1–3 atomic.

**Task 1** — The verify command depends on Task 2's tests, and the spec doesn't say how `tasks_in` imports the helper.
`-k record_pr` selects only tests that Task 2 adds or that already exist. If none exist, pytest exits with "no tests ran" (exit code 5), so the check can't pass or fail meaningfully. The spec also doesn't say whether `tasks_in` gets `slug_from_url` by import from `lib/git.py` or by some other route. It never says how a PR repository is turned into a slug either: whether the PR value is already `owner/name` or a URL that also needs normalising.

Fix: put the tests before the implementation, and state the import and the PR-side format (URL or slug) in the task.

**Task 2** — It has no verify command, and "rows" is vague.
The task says to add "rows" for four cases without naming the test function or parametrisation they go into. It gives no expected `owner/name` outputs and no run command. The spec doesn't say whether the new rows test `slug_from_url` directly or go through `record-pr`.

Fix: name the test function and the expected slugs, and add a verify command.

**Spec** — None of the named paths could be verified, because the working directory has no files except SPEC.md.
`.agent/tools/task/task_record_pr.py`, `tasks_in`, `.agent/tools/lib/git.py`, `evals/test.sh` and `evals/tools/test_lifecycle.py` were all unconfirmed. A Glob for `*.py`/`*.sh` returned nothing, and Grep found `slug_from_url`/`repo_remote_url` only in SPEC.md. If the files don't exist, the builder has no way to run the Tests section.

Fix: confirm each path exists in the target repo, or say in the spec that the case files will supply them.

**Acceptance criteria** — The bullets have no `verify:` or inspection path, and they omit `None` handling.
Neither bullet names a command or a file to inspect, so the builder can't mark it `[x]` mechanically. `slug_from_url` returns `str | None`, but nothing says what `tasks_in` does when it returns `None` (an unparseable or missing `repo_remote_url`), so a task with no remote could match a PR with no slug.

Fix: add a `verify:` command to each bullet, plus a criterion that a `None` slug never matches.

Verdict: 5 finding(s), 1 unverified: the five file paths named in the Spec finding (the PR-repository format in `tasks_in` also went unchecked).