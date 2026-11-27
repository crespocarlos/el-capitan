Assessment: request-changes — the `pr` step's hold check is `bool(value)`, so a PR that was closed or never merged still counts as done on a re-run, which breaks the "re-checking the earlier ones" promise.

1. [attention · 4] **`.agent/tools/task/task_ship.py:31`** (pr step hold) — a closed PR counts as a shipped PR
```
"push": push_holds, "pr": lambda _, value: bool(value), "done": done_holds}
```
Every other step is re-verified against real state. The `pr` step only checks that a URL string was recorded earlier. Suppose the owner or a reviewer closes the PR, or it was opened against the wrong base, and the owner then fixes the cause and re-runs `ship`. The run prints `ship: pr already done (<url>)` and carries on to `done`, which marks the task DONE. Nothing is open for review, and the owner is told it shipped. `open_pr` already filters on `--state open`, so it would open a fresh draft PR. It is never called because the hold check short-circuits it.
Fix: make the `pr` hold query the PR's current state, for example `gh pr view <url> --json state --jq .state`, and treat it as holding only when the state is `OPEN`. Decide separately whether a merged PR should also count as holding.

2. [nit · 3] **`.agent/tools/task/task_ship.py:9`** — a failed PR lookup is treated as "no PR exists"
```
existing = pr_url(listed.stdout) if listed.returncode == 0 else ""
```
If `gh pr list` fails, for example from an auth or network blip, the code goes on to `pr create` without saying the lookup failed. If an open PR already exists, the owner then gets a confusing "gh pr create failed" error that doesn't mention the real cause. Print the list error, or stop with it, so the owner can recover.

Criteria: no spec was provided, so none were walked. The idempotency promise in the change description ("re-checking the earlier ones") is contradicted for the `pr` step.