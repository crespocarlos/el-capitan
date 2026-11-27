Assessment: request-changes — the close move is offered for states outside the stale set the spec lists, including ABANDONED, and it can turn an owner-dropped task into DONE.

1. [attention · 4] **`tui/tui_model.py:21`** — close-as-done is offered for ABANDONED and unset or unreadable states, not just the stale set
```
if state != "DONE" and not (state == "IMPLEMENTING" and prs):
    found.append(Move("close as done (mark-done --force)", ...
```
The change says the move is for DRAFTING, APPROVED, ON-HOLD, or IMPLEMENTING without a PR. The guard is a negation (`!= "DONE"`), so it also matches ABANDONED, `""` (no status set) and anything `read_status` returns that isn't a listed state. `task_status.py` defines ABANDONED as "dropped, never to be finished" and sets it only for the owner. Offering "close as done" on an abandoned row lets a dashboard user turn a deliberately dropped task into DONE, recorded as "closed: stale". That misreports the task's history. The CLI may still refuse some of these, but the menu shouldn't offer a move the spec excludes. `blocked` has the same `!= "DONE"` pattern. That part isn't new, but this diff extends it.
Fix: allow the move only for an explicit set, `state in ("DRAFTING", "APPROVED", "ON-HOLD") or (state == "IMPLEMENTING" and not prs)`. Add a test that ABANDONED and `""` get no close move.

2. [attention · 3] **`tui/tui_model.py:6`** — the default note "closed: stale" is stored as the PR URL and is pre-filled
```
FORCE_NOTE = "closed: stale"
... ask="note", default=FORCE_NOTE))
```
The note is passed as `--pr-url`, so it is stored in the PR field of a DONE task. The old prompt said "note recorded as the PR", which told the user where the text would go. The new prompt just says "note". The spec says the owner "types a short note", but the default means pressing Enter records "closed: stale" with no reason. Many closed tasks will carry that same string, which makes the record useless for telling dropped work apart from finished work. Also, an IMPLEMENTING task with no PR whose work was actually committed to main used to get a fitting note ("none (committed to main)"). Now it is labeled stale.
Fix: restore the prompt wording "note recorded as the PR". Drop the default, or require a non-empty note, so the user's reason is what gets stored.

3. [nit · 3] **`tui/tui_model.py:22`** — no confirmation or distinct label for an irreversible state change
The row label "close as done (mark-done --force)" reads like a routine action. It forces DONE past the PR gate, and the diff shows no way back out of DONE. A mis-pick from a list that now also holds "blocked" and the gate move costs a wrongly DONE task.
Fix: label it "close as done without a PR" and/or add a confirm step after the note.