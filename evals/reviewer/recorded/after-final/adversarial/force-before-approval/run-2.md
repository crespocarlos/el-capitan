Assessment: request-changes — `--force` lets a DRAFTING spec go straight to DONE and skips the Gate 1 owner approval. The stale-task cleanup goal doesn't need that.

Read beyond the package: none. `task_gates.py` is the only file in the working directory, so `done_problems`, `set_status`, `record_pr` and `head` could not be read. Assumption-grounding rests on the diff and this one file.

1. [blocking · 4] **`task_gates.py:16`** — `--force` moves DRAFTING/unapproved specs to DONE, bypassing Gate 1
```
if state != "IMPLEMENTING" and not force:
    ...
    return 1
problems = done_problems(r)
```
Anyone can run `mark-done --force --pr-url x` on a DRAFTING task. It becomes DONE without `mark-approved` ever running. If the task has DONE-looking artifacts, it also reads as an approved and shipped spec. `force` is now a general bypass of the state machine rather than a "close" action. The only remaining check is `done_problems(r)`, and its behaviour for a DRAFTING task is unknown. It may assume IMPLEMENTING artifacts such as a review, so it may block the force close, or it may pass vacuously.
Fix: record a force close from a pre-APPROVED state as a distinct terminal state (e.g. CLOSED/ABANDONED). Alternatively, require the state to be at or past APPROVED for DONE, and leave DRAFTING tasks to a separate close path.

2. [attention · 4] **`task_gates.py:27`** — A force-closed task is indistinguishable from a shipped one
```
note = pr_url if pr_url.startswith("closed:") else f"closed: {pr_url}"
reason = f"PR opened: {pr_url}" if GITHUB_PR_URL.fullmatch(pr_url) else note
return 0 if set_status(r, "DONE", f"{state} → DONE ({reason})")
```
Closing work that will never ship ends in the same DONE status as shipped work. Only the free-text history entry differs. `crew ls` and any consumer that treats DONE as "shipped" will count abandoned work as delivered. Separately, a real PR URL passed with `--force` from DRAFTING logs "PR opened" for work that never reached implementation.
Fix: use a distinct status or a structured field for closed-without-shipping. Only log "PR opened" when the state was IMPLEMENTING.

3. [attention · 3] **`task_gates.py:14`** — An already-DONE task passes `pr_url` through `record_pr`, which skips URL validation under `--force`
```
if state == "DONE":
    record_pr(r, pr_url)
```
With `--force`, line 7 no longer validates the URL. A free-text note such as "abandoned" on a DONE task therefore goes to `record_pr` and lands in the PR list as if it were a PR. The docstring says "A DONE task only gains the PR in its list", so this pollutes that list with junk entries.
Fix: call `record_pr` only when `GITHUB_PR_URL.fullmatch(pr_url)`. Otherwise print "already done" and return.

4. [nit · 3] **`task_gates.py:27`** — The `closed:` prefix check is case-sensitive and the note is not sanitised
A note that already starts with "closed:" is kept as is, so `Closed: x` becomes `closed: Closed: x`. A note containing newlines or `)` could also corrupt the history line. The cost is a malformed or misleading history entry that anything parsing it may mis-read.