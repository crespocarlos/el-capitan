Assessment: request-changes — the `pr` step's hold check never re-checks the PR, so a closed or merged PR is treated as done and the task is marked DONE.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:32`** — `pr` step is "held" by any recorded value, so a closed PR still counts as shipped
```python
STEP_HOLDS = {... "push": push_holds, "pr": lambda _, value: bool(value), "done": done_holds}
```
The change promises that `ship` re-checks earlier steps on every re-run. Every other step has a real check, but `pr` only tests that a URL was recorded. If the owner closes the draft PR, or it gets merged or abandoned, between runs, `ship` prints "pr already done (<url>)" and moves on to `done`. The task is then marked DONE with no open PR for review. `open_pr` already lists only `--state open` and would open a new PR, but it is never reached. The owner is told the work shipped when nothing is waiting for review, and re-running `ship` cannot fix it.
Fix: replace the lambda with a `pr_holds(ship, url)` that runs `gh pr view <url> --json state --jq .state` and returns true only for `OPEN`. If `gh` fails, return false so `open_pr` re-lists and reuses the existing PR or creates a new one.

2. [attention · 3] **`.agent/tools/task/task_ship.py:10`** — a failed `gh pr list` is treated as "no PR exists" and falls through to create
```python
existing = pr_url(listed.stdout) if listed.returncode == 0 else ""
```
A transient failure of `gh pr list` (auth, network, rate limit) is silently read as "no PR". The code then goes on to `gh pr create`. If a PR is already open, that call fails with a confusing "already exists" error, or in some cases creates a duplicate. The owner never sees that the real failure was the lookup. Separately, the list uses `--head ship.branch` while create uses `ship.head_ref`. If those differ, for example on a fork, the existing-PR check can miss the PR it should find.
Fix: if `listed.returncode` is non-zero, `raise Stop(f"gh pr list failed: {listed.stderr.strip()}")` so the owner can fix the cause and re-run. Use the same head value in both calls.