Assessment: request-changes — the "re-check earlier steps" promise fails for the `pr` step, so a re-run can mark a task DONE with no open PR.
Read beyond the package: none (the directory holds only `task_ship.py`, so `stage_holds`, `done` and the other helpers can't be checked).

Criteria: 2 satisfied, 1 contradicted, 1 unverified. The criteria come from the change description, since there is no ticket.
- Satisfied: `ship` is idempotent and resumes from a recorded step.
- Satisfied: `open_pr` reuses an open PR instead of creating a duplicate.
- Contradicted: "re-checking the earlier ones" does not hold for `pr`.
- Unverified: whether the other step checks (`stage_holds` and the rest) behave correctly, because they are not in the package.

The person affected is the task owner running `ship` at a terminal. They trust the output "already done" and the DONE status.

1. [blocking · 4] **`.agent/tools/task/task_ship.py:34`** (h1) — `pr` step "holds" whenever a URL was recorded, even if the PR is now closed
```python
STEP_HOLDS = {... "push": push_holds, "pr": lambda _, value: bool(value), "done": done_holds}
```
The owner ships and a draft PR is opened and recorded. The PR is then closed, for example by a reviewer, or it is merged or deleted. The owner fixes something and re-runs `ship`. `bool(value)` is true, so the output reads `ship: pr already done (https://…/pull/12)`. The `done` step then runs and the task is marked DONE with no open PR. `open_pr` already lists only `--state open` PRs, so it would create a new PR, but it is never reached. Every other step is re-verified against real state, and `pr` is the only one that is not. The same applies if the branch was force-pushed after the PR closed. This is not pre-existing; the diff introduces it.
Fix: make the `pr` hold check ask GitHub whether that PR is still open, for example with `gh pr view <url> --json state`. Treat any other state, or a failed lookup, as not holding so `open_pr` runs again. Print a distinct message when a recorded PR turns out to be closed.

2. [attention · 3] **`.agent/tools/task/task_ship.py:10`** (h1) — a failed PR lookup is treated as "no PR" and a duplicate PR can be created
```python
existing = pr_url(listed.stdout) if listed.returncode == 0 else ""
```
If `gh pr list` fails because of a network error, an auth error or rate limiting, the code silently falls through to `gh pr create`. When a PR is already open, the user then gets a confusing create error or a duplicate. The lookup failure is never shown to them.
Fix: if `listed.returncode` is non-zero, raise `Stop` with the stderr from `gh pr list` and tell the owner to re-run `ship` once the lookup works.

3. [nit · 2] **`.agent/tools/task/task_ship.py:43`** — a step that is rerun prints no reason
The output shows `already done` for skipped steps. A step that no longer holds simply runs, with no line like "merge no longer holds, re-running". The owner can't tell resumed work from a first run. The cost is some confusion when diagnosing a re-run.