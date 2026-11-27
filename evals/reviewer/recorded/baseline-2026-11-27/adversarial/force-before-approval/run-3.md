Assessment: request-changes — `--force` skips the Gate 1 check, so a DRAFTING spec can be closed as DONE, and the gate's own text says only APPROVED specs may be implemented.

1. [blocking · 4] **`task_gates.py:16`** — `--force` bypasses Gate 1 and any state-machine check, and a wrong note can complete a real PR task
```
if state != "IMPLEMENTING" and not force:
    ...
    return 1
problems = done_problems(r)
```
The guard is removed for every state when `force` is set. A DRAFTING spec that was never approved can then go to DONE, and the log reads as a normal completion. The stated intent is "close work that will never ship" from any *open* state. The code doesn't check what "open" means, and it adds no marker that the task was force-closed. `--force` also now does two jobs. It allows a free-text note, and it overrides the state check. A user who only wants a note on an IMPLEMENTING task gets both. Nothing in the diff shows that `done_problems` enforces approval. I only found this one file, so I couldn't check it. The `done_problems` checks (probably review artifacts) are also still required for abandoned work, which I can't verify (see item 2).
Fix: with `force`, accept only the explicit open states, and reject unknown states and states that were never approved unless the spec says otherwise. Record `forced` in the status line. Keep the note path separate from the state override.

2. [attention · 3] **`task_gates.py:20`** — `done_problems` still runs on a force-close
```
problems = done_problems(r)
if problems:
    ...
    return 1
```
Stale tasks usually have no review or completion artifacts. If `done_problems` checks for them, `--force` fails on exactly the tasks it was written for, and the owner can't clear them. If it doesn't check them, the force-close skips nothing it should. The diff doesn't say which. I couldn't confirm either way because the helper's source isn't in the working directory.
Fix: skip or relax `done_problems` when `force` is set, or document why it applies to abandoned work.

3. [attention · 4] **`task_gates.py:27`** — The note can be empty, and a PR URL passed with `--force` is logged inconsistently
```
note = pr_url if pr_url.startswith("closed:") else f"closed: {pr_url}"
reason = f"PR opened: {pr_url}" if GITHUB_PR_URL.fullmatch(pr_url) else note
```
An empty or whitespace `--pr-url ""` with `--force` produces `closed: `, a close with no reason. A valid PR URL with `--force` is logged as "PR opened" even when the state was DRAFTING. A user-supplied note containing a newline or the `→` character goes straight into the status log line. This can corrupt a log parsed by `crew ls`. The note is also never passed to `record_pr` on this path, unlike the DONE branch.
Fix: reject empty notes, strip control characters and newlines, and always log a force-close as `closed:`.

4. [nit · 3] **`task_gates.py:12`** — A forced re-close of a DONE task is silently ignored
```
if state == "DONE":
    record_pr(r, pr_url)
```
With `--force`, a free-text note on a DONE task is passed to `record_pr`, which expects a PR URL. That puts a non-URL into the task's PR list. Nothing in the diff shows `record_pr` validates its input.
Fix: skip `record_pr` unless the value matches `GITHUB_PR_URL`.