Assessment: request-changes — the `pr` step's hold check is `bool(value)`, so a closed or deleted PR still counts as shipped. That breaks the re-check-earlier-steps promise, and `ship` can then mark the task DONE with no live PR.

Read beyond the package: none (the working directory holds only this diff, so `recorded_steps`, `done_holds` and `gh` are unread).

The person here is the task owner running `ship` again after a stop. Criteria: the spec text isn't in the package, so I judged against the change description's idempotency promise: "continues from the first step that no longer holds, re-checking the earlier ones".
Criteria: 0 satisfied, 1 partially satisfied, 1 contradicted, 0 unverified

1. [blocking · 4] **`.agent/tools/task/task_ship.py:33`** — `pr` step "holds" for any recorded URL, even if the PR is closed
```
STEP_HOLDS = {... "pr": lambda _, value: bool(value), "done": done_holds}
```
The owner ships, the PR is opened and recorded, then the reviewer closes it, or it is deleted or merged, and the owner runs `ship` again. Every earlier step holds, and `pr` holds because the recorded string is non-empty. The run prints `ship: pr already done (<url>)` and carries on to `done`. The task is marked DONE with no live PR, so the output reports success that is false. `open_pr` already has a live-PR check, but it is never reached on a re-run. This contradicts the "re-checking the earlier ones" promise.
Fix: make `pr` hold only when the recorded URL is still open, for example `gh pr view <url> --json state --jq .state` equal to `OPEN`. Otherwise fall through to `open_pr`. Decide what a merged PR means: either treat it as done, or stop with a clear message.

2. [attention · 3] **`.agent/tools/task/task_ship.py:9`** — a failed `gh pr list` falls through to `gh pr create`
```
existing = pr_url(listed.stdout) if listed.returncode == 0 else ""
```
After a network or auth hiccup, the list call fails and its error is discarded. The code then tries to create a PR. If a PR already exists, the owner sees only a confusing "gh pr create failed" message, or in some setups gets a duplicate. The root cause, which is the list failure, is never shown.
Fix: if `listed.returncode` is non-zero, `raise Stop(f"gh pr list failed: {listed.stderr.strip()}")`.

3. [attention · 2] **`.agent/tools/task/task_ship.py:10-13`** — the lookup uses `--head ship.branch` but creation uses `ship.head_ref`
```
"--head", ship.branch ...   vs   "--head", ship.head_ref
```
If `head_ref` is `owner:branch` (a fork), the lookup by bare branch may not find the PR it created. A re-run could then try to create a second PR, which errors out. I could not confirm the fork case without seeing `Ship`.
Fix: use the same head identifier in both calls.