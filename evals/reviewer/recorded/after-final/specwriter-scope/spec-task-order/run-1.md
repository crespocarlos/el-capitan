**Task 1** — Task 1 depends on a function that Task 3 creates: "compare `slug_from_url(r.meta["repo_remote_url"])`"

The builder runs Task 1 first, and `slug_from_url` doesn't exist yet. The edit fails with a NameError or ImportError, and the `-k record_pr` verify fails. The builder can burn its three verify attempts before Task 3 runs. Glob and Grep found no `slug_from_url` anywhere in the case files, so Task 3 is the only task that supplies it.

Move Task 3 (add `slug_from_url`) before Task 1. Task 1 should also say to import it from `.agent/tools/lib/git.py`.

**Task 2** — Task 2 has no verify line, and it comes before the code it tests: "add rows for ssh, https, `.git` and case to `evals/tools/test_lifecycle.py`"

The builder can't tell whether the rows pass or fail. Placed before Task 3 or Task 1, the new rows would fail. Task 2 also leaves the three-way match open: the spec doesn't say whether rows go in the existing record_pr tests or a new test.

Order the tasks 3, 1, 2. Give Task 2 an explicit verify line, `bash evals/test.sh evals/tools/test_lifecycle.py -k record_pr`. Name the existing test function or table the rows join.

**Task 3** — Task 3 has no verify line and no direct test of `slug_from_url`: "add `slug_from_url(url) -> str | None` to `.agent/tools/lib/git.py` (ssh, https, `.git`, case)"

The helper's return value is only checked indirectly, through the record_pr tests in Task 2. A normalisation bug such as a trailing slash or a non-GitHub host can't be traced to its task. The spec also doesn't say what `None` means for Task 1's comparison. A task with an unparseable URL could match a PR with no repository, because `None == None`.

Add a verify line that imports and calls the function, or a unit test for it. Say in Task 1 how `None` is handled, so it never matches.

**Spec-level** — The paths and the test command are unverified, and the case files hold no code

Glob found none of `.agent/tools/task/task_record_pr.py`, `.agent/tools/lib/git.py`, `evals/tools/test_lifecycle.py` or `evals/test.sh`. The builder can't confirm `tasks_in` exists, that `r.meta` is the right structure, or that `-k record_pr` selects any test. If it selects none, the check passes without testing anything.

Add a criterion or note that `-k record_pr` must select at least one test. Confirm the paths exist before the spec is presented to the user.

Verdict: 4 finding(s), 4 unverified: `.agent/tools/task/task_record_pr.py`, `.agent/tools/lib/git.py`, `evals/tools/test_lifecycle.py`, `evals/test.sh`