**Task 1** — Task 1 calls a helper that Task 3 creates, so the order is wrong.

Task 1 uses `slug_from_url`, but Task 3 adds it to `.agent/tools/lib/git.py`. Task 1's verify command (`-k record_pr`) would fail with an ImportError or NameError. Task 2's new rows would also fail until Task 3 is done. The spec doesn't declare these tasks atomic.

Fix: Put the helper first (Task 3 becomes Task 1), then the `tasks_in` change, then the tests. Alternatively, mark the tasks atomic.

**Task 2** — Task 2 has no verify command, and its test rows depend on later work.

The rows test behaviour that doesn't exist at that point in the order. The task also doesn't name the test function or say what the rows should contain. For example, it doesn't say whether the ssh rows go through `slug_from_url` directly or through `record-pr`.

Fix: Add a `Verify:` command, and state which test function or table the rows go in and the expected slug for each row.

**Task 3** — The helper's behaviour is underspecified, so the acceptance criteria can't be checked.

The spec gives no output format. It doesn't say whether the slug is lowercased. It doesn't say what `None` means, or how it handles `ssh://` URLs, trailing slashes, or non-GitHub hosts. Task 1 also doesn't say how to handle a `None` result from a task or PR URL, or what form the "PR's repository" takes. That could be a URL or an `owner/name` string.

Fix: Define the input-to-slug mapping, including the `None` cases. Say what `tasks_in` does when either side returns `None`. Also say whether the PR repository is passed through `slug_from_url` as well.

**Tests** — The test command and the file paths are unverified, and the spec doesn't say how the tests run.

Glob found none of `.agent/tools/task/task_record_pr.py`, `.agent/tools/lib/git.py`, `evals/tools/test_lifecycle.py` or `evals/test.sh` in the working directory. Grep found no `tasks_in` or `repo_remote_url` outside SPEC.md. Without them the builder can't confirm that `-k record_pr` selects any tests. The spec also has no `###` subsection for the new helper's own unit tests, and no doc task, though that may be waivable.

Fix: Confirm the paths against the repo root. Make sure the `-k` selector matches test names that Task 2 adds.

Verdict: 4 finding(s), 4 unverified: `task_record_pr.py`, `lib/git.py`, `test_lifecycle.py` and `evals/test.sh` were not found in the working directory. `tasks_in` and `repo_remote_url` also weren't found outside SPEC.md.