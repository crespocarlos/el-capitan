Assessment: request-changes: the `pr` step's hold check never looks at the PR, so a re-run can mark the task DONE against a closed PR, which breaks the promise that ship re-checks earlier steps.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:30`** — `pr` step "holds" for any recorded URL, even if the PR was closed
```python
STEP_HOLDS = {... "push": push_holds, "pr": lambda _, value: bool(value), "done": done_holds}
```
The spec says ship "continues from the first step that no longer holds, re-checking the earlier ones". For `pr`, the hold check only tests that a URL string was recorded. Suppose the owner or a reviewer closes the draft PR after a stop, or it gets merged or abandoned. The owner then fixes the cause and re-runs `ship`. The run prints `ship: pr already done (<url>)` and goes on to `done`, so the task is marked DONE pointing at a PR nobody will review. The owner gets no warning. This is also inconsistent with `open_pr`, which only treats an *open* PR as reusable (`--state open`). Because of the lambda, that code never runs on a re-run once a URL is recorded.
Fix: make `pr_holds(ship, url)` query `gh pr view <url> --repo ship.target --json state,headRefName` and return true only when the state is `OPEN` and the head is `ship.branch`. If the PR is closed, fall through to `open_pr` so a new one is created, or stop with a message saying the PR was closed. The same check should cover a merged PR.

2. [attention · 3] **`.agent/tools/task/task_ship.py:10`** — a failed `gh pr list` silently falls through to `pr create`
```python
existing = pr_url(listed.stdout) if listed.returncode == 0 else ""
```
When the lookup fails (network error, auth problem, rate limit), the code treats that as "no PR exists" and calls `gh pr create`. If a PR is already open, the create call fails with an unclear error. The owner sees "gh pr create failed", not the real cause, which was the failed lookup. The two calls also use different head arguments: `ship.branch` for the list and `ship.head_ref` for the create. For a fork-style `owner:branch` ref, the existing PR could be missed, and a duplicate attempt would follow.
Fix: if `listed.returncode` is non-zero, raise `Stop(f"gh pr list failed: {listed.stderr.strip()}")`. Use the same head value for both calls.

Criteria: no spec or ticket was provided beyond the change description. Idempotent resume with re-checking of earlier steps is contradicted for the `pr` step (finding 1). The other steps are unverified because their hold functions are not in the diff.