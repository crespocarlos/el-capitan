**Task 1** — depends on `slug_from_url`, which Task 3 creates: "compare `slug_from_url(r.meta["repo_remote_url"])` with each PR repository. Verify: `bash evals/test.sh evals/tools/test_lifecycle.py -k record_pr`"

Task 1 imports a function that doesn't exist until Task 3. Its verify line therefore fails with an ImportError or NameError on every run, and the builder marks the task failed after three runs.

Fix: reorder to Task 3 (add `slug_from_url`), then Task 1 (use it), then Task 2 (tests), or merge the tests into the tasks that create each behavior.

**Task 2** — has no verify line, and its rows depend on both other tasks: "add rows for ssh, https, `.git` and case to `evals/tools/test_lifecycle.py`."

The builder has no pass/fail check for this task. Placed before Task 3, the new rows can't pass.

Fix: add a verify line (for example `bash evals/test.sh evals/tools/test_lifecycle.py -k record_pr`) and place the task after the implementation tasks. Alternatively, write the tests first and mark Tasks 2 and 1 as atomic.

**Task 3** — has no verify line and sits last, so the tree is broken if the loop stops earlier: "add `slug_from_url(url) -> str | None` to `.agent/tools/lib/git.py` (ssh, https, `.git`, case)."

If the loop stops after Task 1, `task_record_pr.py` calls a missing function, so `record_pr` is broken. The `| None` return also doesn't say how Task 1 should handle an unparseable URL, such as a local path or a missing `repo_remote_url`.

Fix: make this Task 1 with its own verify line, and state in Task 1 what to do when the slug is `None`.

**## Tests / Unit** — the paths and the test command could not be verified, and the section may not cover the boundary: "`bash evals/test.sh evals/tools/test_lifecycle.py`"

Glob found no `evals/test.sh`, `evals/tools/test_lifecycle.py`, `.agent/tools/task/task_record_pr.py` or `.agent/tools/lib/git.py` in the working directory, and `tasks_in` is not defined anywhere I could search. If the files aren't there, every verify line stalls. `record-pr` is also a CLI that other scripts call, so a Unit-only section may miss the layer that crosses that boundary.

Fix: confirm the four paths and the `-k record_pr` selector exist, and add an integration check that runs `record-pr` end to end if that is the real entry point.

**Acceptance criteria** — neither bullet names how the builder proves it: "`.git` suffixes and letter case do not matter."

The bullets say nothing about which test row or command proves them, so the builder can't confirm they're met.

Fix: tie each criterion to a named test case in `evals/tools/test_lifecycle.py`, for example "`pytest -k record_pr` passes the ssh-vs-https row".

Verdict: 4 finding(s), 4 unverified: `.agent/tools/task/task_record_pr.py`, `.agent/tools/lib/git.py`, `evals/tools/test_lifecycle.py`, `evals/test.sh`