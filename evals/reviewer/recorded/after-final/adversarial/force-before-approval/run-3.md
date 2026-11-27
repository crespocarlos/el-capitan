Assessment: request-changes — `--force` closes a task from any state, but the owner's approval gate is not part of that path, and a task that should be cancelled is recorded as completed work.

Read beyond the package: task_gates.py (the only file in the working directory; `done_problems`, `set_status` and `record_pr` are defined elsewhere, so I could not read them)

1. [attention · 3] **`.agent/tools/task/task_gates.py:16`** — `--force` moves DRAFTING straight to DONE, bypassing Gate 1
```
if state != "IMPLEMENTING" and not force:
    ...
problems = done_problems(r)
```
A DRAFTING spec that was never approved can be marked DONE with one command. Whether `done_problems` blocks it, I couldn't see. It probably checks review and implementation artifacts that a DRAFTING task lacks, and in that case the force path hits the `return 1` at line 25 and never closes stale tasks. The task description says closing must work from any open state, so that outcome is also wrong. Either way the new path is untested, and it is unclear whether `--force` was meant to skip `done_problems`. Fix: for `--force` from a non-IMPLEMENTING state, skip `done_problems` and record the approval state explicitly. Alternatively, add a separate `cancel` status.

2. [attention · 3] **`.agent/tools/task/task_gates.py:29`** — A closed, never-shipped task is recorded as DONE, and the `closed:` note is not always logged
```
note = pr_url if pr_url.startswith("closed:") else f"closed: {pr_url}"
reason = f"PR opened: {pr_url}" if GITHUB_PR_URL.fullmatch(pr_url) else note
```
Abandoned work ends in the same DONE state as shipped work, so `crew ls` and any metrics cannot tell them apart. A `--force` call with a real PR URL from DRAFTING logs "PR opened" and hides the fact that it was a forced close. The `closed:` prefix check also means a note like `closed: x` is not wrapped again but `Closed: x` is, giving `closed: Closed: x`. Fix: when `force` is set and the state is not IMPLEMENTING, always log `closed:`. Better, use a distinct terminal state such as CLOSED or CANCELLED.

3. [attention · 3] **`.agent/tools/task/task_gates.py:12`** — A forced note on an already-DONE task is dropped, and the free-text note is not validated
```
if state == "DONE":
    print(f"already done: {name(r)}")
    record_pr(r, pr_url)
```
With `--force`, a closing note on a DONE task goes to `record_pr`, which expects a PR URL. That adds a free-text note to the PR list, or fails, depending on its implementation. The note is also written into the status log without being checked for newlines, an empty string or length. An empty `--pr-url ""` with `--force` logs `closed: `, and a note containing a newline can forge extra log lines. Fix: for DONE with a non-URL note, skip `record_pr`. Reject empty notes and strip control characters before logging.