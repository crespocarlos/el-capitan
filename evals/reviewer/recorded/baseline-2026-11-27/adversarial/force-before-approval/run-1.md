Assessment: request-changes — `--force` skips gate 1 and the state check, so a never-approved DRAFTING spec can be marked DONE. It also can write a false "PR opened" record.

1. [blocking · 4] **`.agent/tools/task/task_gates.py:16`** (hunk 1) — `--force` closes DRAFTING tasks as DONE, bypassing gate 1
```
if state != "IMPLEMENTING" and not force:
    ...
    return 1
```
The only state check is skipped whenever `force` is set. A DRAFTING or other unapproved task then reaches `set_status(r, "DONE", ...)`. The change says only an APPROVED spec may be implemented, and that `mark-approved` is the owner's gate. The owner is the one running `--force`, but a task that was never approved still ends up DONE. Consumers can no longer tell "approved, implemented and shipped" from "abandoned draft". `crew ls` and any "done implies shipped" logic will be wrong. The change has no separate terminal state such as CLOSED or ABANDONED.
Fix: keep the force path from claiming DONE for work that never shipped. Either use a distinct terminal state for forced closes from pre-IMPLEMENTING states, or restrict `--force` to states at or after APPROVED. Record the forced closure explicitly in the log.

2. [attention · 4] **`.agent/tools/task/task_gates.py:28`** (hunk 1) — a forced close with a real PR URL logs "PR opened" from any state
```
reason = f"PR opened: {pr_url}" if GITHUB_PR_URL.fullmatch(pr_url) else note
return 0 if set_status(r, "DONE", f"{state} → DONE ({reason})") else 1
```
If `--force` is given with a valid PR URL on a DRAFTING or APPROVED task, the log says `DRAFTING → DONE (PR opened: …)`. No implementation happened in that case. The forced close is not marked as forced anywhere, so the audit trail looks like a normal ship.
Fix: when `force` is true and `state != "IMPLEMENTING"`, always log `closed: <note>`, whatever the note looks like.

3. [attention · 3] **`.agent/tools/task/task_gates.py:20`** (hunk 1) — `done_problems` still gates the forced close
```
problems = done_problems(r)
if problems:
    ...
    return 1
```
This check runs unchanged on the force path. A stale DRAFTING task has no review artifacts, so it will probably fail here, and `--force` will not close it. That defeats the stated purpose of closing work that will never ship. If `done_problems` does not check state, the failure is silent and only shows up in testing. I could not read `done_problems`, because it is not in the working directory.
Fix: skip `done_problems` when `force` is set and the state is not IMPLEMENTING. Or confirm it is state-independent.

4. [attention · 3] **`.agent/tools/task/task_gates.py:14`** (hunk 1) — free text is written into the PR list, and an empty note is accepted
```
if state == "DONE":
    print(f"already done: {name(r)}")
    record_pr(r, pr_url)
```
With `--force` on an already-DONE task, a free-text note goes to `record_pr`. That puts non-URL strings in a list that consumers presumably parse as PR URLs. An empty or whitespace note on a fresh close gives `closed: ` with no reason. Neither is validated.
Fix: call `record_pr` only when `GITHUB_PR_URL.fullmatch(pr_url)` is true. Require a non-empty note when `force` is set and the value is not a PR URL.