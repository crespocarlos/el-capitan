Assessment: request-changes — `--force` on a DRAFTING or other unapproved task jumps it to DONE with no guard, so the change goes past "close stale tasks" and bypasses Gate 1.

1. [blocking · 4] **`.agent/tools/task/task_gates.py:16`** — `--force` lets DRAFTING skip Gate 1 and land in DONE
```python
if state != "IMPLEMENTING" and not force:
    print(f"error: {name(r)} is {state}, not IMPLEMENTING; nothing written (--force closes it)",
```
The state guard is bypassed for every state, so a DRAFTING (unapproved) spec goes straight to DONE. The stated invariant is that only the owner's `mark-approved` moves DRAFTING to APPROVED. Nothing in this function checks who is calling or that the task was approved, so any caller who passes `--force` can finish unapproved work. The audit line `DRAFTING → DONE (closed: ...)` also reads as a legitimate completion. Whether `done_problems` blocks this is unverified: I couldn't find its definition in the working directory, and it runs before the write, so it may reject non-IMPLEMENTING tasks.
Fix: with `--force`, require the state to be an explicit open set. If DRAFTING must be closable, do it through a separate cancel path that records a distinct status such as CLOSED/CANCELLED rather than DONE. At minimum, require a non-empty note.

2. [attention · 4] **`.agent/tools/task/task_gates.py:28`** — A real PR URL passed with `--force` is logged as "PR opened" regardless of state
```python
reason = f"PR opened: {pr_url}" if GITHUB_PR_URL.fullmatch(pr_url) else note
return 0 if set_status(r, "DONE", f"{state} → DONE ({reason})") ...
```
A task that was never implemented (say DRAFTING) gets a log entry claiming a PR was opened. The log can no longer tell a shipped task from a force-closed one. That defeats the point of the `closed: <note>` convention.
Fix: log "PR opened" only when `state == "IMPLEMENTING"`. Otherwise always log `closed: <note>`.

3. [attention · 3] **`.agent/tools/task/task_gates.py:14`** — A free-text note can reach `record_pr` on an already-DONE task
```python
if state == "DONE":
    print(f"already done: {name(r)}")
    record_pr(r, pr_url)
```
With `--force`, the PR-URL validation at line 7 is skipped, so `pr_url` can be arbitrary text. On an already-DONE task that text is passed to `record_pr` and appended to the PR list. Before this change, only validated URLs reached this line. Consumers that parse that list as URLs may break. I couldn't read `record_pr`, so I don't know if it validates.
Fix: call `record_pr` only when `GITHUB_PR_URL.fullmatch(pr_url)` matches. Otherwise just print "already done".

4. [nit · 3] **`.agent/tools/task/task_gates.py:27`** — The note is not checked for empty or multi-line input
`note = pr_url if pr_url.startswith("closed:") else f"closed: {pr_url}"` accepts `--pr-url ""` and values with newlines. The result is a blank `closed: ` entry or an injected extra log line.
Fix: reject an empty note under `--force`, and strip newlines from it.