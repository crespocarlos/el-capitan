Assessment: request-changes — the `pr` step's hold check never re-checks the PR, so a re-run after the PR is closed reports it "already done" and marks the task DONE.

Read beyond the package: none (the working directory holds only this excerpt).

Criteria: 0 satisfied, 1 partially satisfied, 0 contradicted, 0 unverified. The one criterion is the change description's claim that `ship` "continues from the first step that no longer holds, re-checking the earlier ones". It is partially satisfied: `stage`, `commit`, `merge`, `test`, `push` and `done` each have a real check, but `pr` does not.

The person affected is the task owner running `crew-task.py ship` again after a stop.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:32`** — `pr` hold check only tests that a URL was recorded, so a closed PR still counts as shipped
```
"push": push_holds, "pr": lambda _, value: bool(value), "done": done_holds}
```
The owner ships, the draft PR is opened, and the URL is recorded. The PR is then closed (or merged, or deleted), and the owner re-runs `ship` to fix something. The `pr` step prints "ship: pr already done (<url>)" and skips `open_pr`, even though `open_pr` itself lists only `--state open` PRs. If `done` doesn't hold, the task is marked DONE with no open PR. Every other step re-verifies against live state, so this one breaks the idempotency promise and misreports the outcome. The same gap applies to a PR whose head branch changed after a later push step re-ran.
Fix: make the `pr` hold check query `gh pr view <url> --json state,headRefName` (or reuse the `gh pr list --state open --head` lookup). It should return true only if the PR is still open on `ship.branch`; otherwise `open_pr` runs and creates a new PR.

2. [attention · 3] **`.agent/tools/task/task_ship.py:10`** — a failed `gh pr list` silently falls through to `pr create`
```
existing = pr_url(listed.stdout) if listed.returncode == 0 else ""
```
When the list call fails (auth error, network failure, rate limit), the code behaves as if no PR exists and tries to create one. If a PR is already open, the owner sees a confusing "gh pr create failed: a pull request already exists" instead of the real cause. The list error is discarded.
Fix: if `listed.returncode` is non-zero, `raise Stop(f"gh pr list failed: {(listed.stderr or listed.stdout).strip()}")`.