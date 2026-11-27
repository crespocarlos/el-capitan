Assessment: request-changes — `--force` can mark any task DONE from any state, and it can mark a non-IMPLEMENTING task DONE with a real PR URL. That bypasses the Gate 1 and implementation ordering the change says it must keep.

Read beyond the package: task_gates.py (the only file present). `done_problems`, `set_status`, `record_pr` and `head` are not defined in the working directory, so I could not check them.

1. [blocking · 4] **`task_gates.py:16`** — `--force` closes from any state, including DRAFTING, and a PR URL then claims "PR opened"
```
if state != "IMPLEMENTING" and not force:
...
reason = f"PR opened: {pr_url}" if GITHUB_PR_URL.fullmatch(pr_url) else note
```
A DRAFTING spec that the owner never approved can be run through `mark-done --force --pr-url https://github.com/o/r/pull/1`. It moves straight to DONE, and the log reads "DRAFTING → DONE (PR opened: …)". That claims a PR was opened for work that never passed Gate 1. The same happens from APPROVED. The `--force` check does not look at who is calling or at the state, so any caller can skip the approval gate. Separately, a real PR URL passed with `--force` from a non-IMPLEMENTING state is recorded as a genuine PR, which is false provenance.
Fix: Under `--force`, allow only a free-text note. Reject a PR-URL-shaped value when `state != "IMPLEMENTING"`, and log it as `closed: <note>` rather than "PR opened". Make sure any `--force` close of an unapproved spec is recorded as a closure, not as completed work.

2. [attention · 3] **`task_gates.py:20`** — `done_problems(r)` still runs under `--force` from states where it was never meant to apply
```
problems = done_problems(r)
if problems:
```
`done_problems` was written for IMPLEMENTING tasks, for example by checking that review artifacts exist. I couldn't read it. A DRAFTING task has no review, so it probably returns problems. In that case the stale-task close this change exists for fails with errors and exit 1. If instead it passes vacuously for those states, that is the same bypass as finding 1. Either way, the forced path was not given its own check.
Fix: Skip `done_problems` for forced closes from non-IMPLEMENTING states, or define the check explicitly for them.

3. [attention · 3] **`task_gates.py:27`** — the note is unsanitized and the `closed:` prefix is conditional
```
note = pr_url if pr_url.startswith("closed:") else f"closed: {pr_url}"
```
A note that already starts with `closed:` is not double-prefixed. Free text containing newlines or `→` goes straight into the status log, which can fake log entries or break parsing of the `state → DONE` line. An empty `--force --pr-url ""` logs "closed: ", an empty reason, and nothing rejects it.
Fix: Reject an empty note, collapse the whitespace and newlines in it, and always use the `closed: ` prefix.

4. [nit · 3] **`task_gates.py:12`** — a DONE task with `--force` and a free-text note calls `record_pr(r, pr_url)`
`record_pr` appends the note to the PR list, so "closed: abandoned" gets stored as a PR. The cost is junk in the PR list, and consumers that expect URLs may break.