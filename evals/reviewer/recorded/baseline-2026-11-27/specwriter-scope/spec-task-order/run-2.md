**Critical**

**Task 1 / Task 3** — Task 1 calls `slug_from_url`, but Task 3 defines it afterward.

Tasks run in order, so Task 1's verify command fails with an ImportError or NameError. Nothing in the spec says the two tasks are atomic.

Fix: put the `slug_from_url` task first, then the `record_pr` change, then the tests. Or mark the tasks atomic.

**Important**

**Task 1** — The spec doesn't say how the PR side is turned into a slug.

The PR's repository is described as `https://github.com/acme/widgets`, and Task 1 compares it with the task's slug without saying whether it is normalised too. If the PR side stays a raw URL, the comparison still fails. The builder also can't tell what type `r.meta` is or whether `repo_remote_url` can be missing. `slug_from_url` can return `None`, and two `None` values would compare equal.

Fix: state that both sides go through `slug_from_url`, and that a `None` result never counts as a match.

**Task 2** — The tests come after the implementation and have no verify command.

Task 1's verify uses `-k record_pr`, which only selects tests that Task 2 adds later. It may select nothing, or pass with no cases. Task 2 has no acceptance check of its own.

Fix: reorder so the test rows come before or with the implementation, and give Task 2 a `verify:` command that names the new test IDs.

**Acceptance criteria** — The two bullets have no verification path.

Neither names a `verify:` command or a test to inspect. The criteria also never say what happens with `None` or unparseable URLs.

Fix: link each bullet to a test ID in `test_lifecycle.py`, for example `verify: bash evals/test.sh evals/tools/test_lifecycle.py -k slug`.

**Consider**

**Spec-level** — I couldn't verify any of the file paths.

The working directory contains only SPEC.md. The paths `.agent/tools/task/task_record_pr.py`, `.agent/tools/lib/git.py`, `evals/tools/test_lifecycle.py`, and `evals/test.sh` aren't present. I also couldn't confirm that `tasks_in` or `slug_from_url` exist, or whether `lib/git.py` already has a similar helper.

Fix: confirm the paths and function names against the real repo.

Verdict: 4 finding(s), 1 unverified: the file paths, `tasks_in`, `slug_from_url`, and `evals/test.sh` are unverified because the case directory contains only SPEC.md.