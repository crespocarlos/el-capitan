Assessment: request-changes — the new "close as done" move is offered from DRAFTING, APPROVED and ON-HOLD, where the GATES comment says the CLI refuses `mark-done`. It also records abandoned work as DONE.

I could not find `crew-task.py` in the working directory, so I could not check what `mark-done --force` accepts. `task_status.py` only defines the states: `STATES` includes DONE, and `SIDE_STATES = ("ABANDONED",)`.

1. [needs more info · 3] **`tui/tui_model.py:20`** — the close move is offered from states the CLI may refuse
```
GATES = (... ("mark-done", "IMPLEMENTING", "mark done"))   # "the CLI refuses any other"
if state != "DONE" and not (state == "IMPLEMENTING" and prs):
    found.append(Move("close as done (mark-done --force)", ("mark-done", ...
```
The GATES comment says each gate moves from one state and "the CLI refuses any other". `mark-done` is gated on IMPLEMENTING, but the new move is offered from DRAFTING, APPROVED and ON-HOLD. If `--force` does not bypass the source-state check, the owner picks the move, types a note, and then gets a CLI error. That is a flow that starts and fails at the end, and the error text is unknown. Does `mark-done --force` accept DRAFTING, APPROVED and ON-HOLD sources? If not, the move must be hidden for those states or the CLI changed.

2. [attention · 3] **`tui/tui_model.py:4`** — stale, never-finished tasks get recorded as DONE
```
FORCE_NOTE = "closed: stale"
...
if state != "DONE" and not (state == "IMPLEMENTING" and prs):
```
The stated purpose is to close stale tasks that were never built, such as DRAFTING or APPROVED. `task_status.py` reserves ABANDONED for "dropped, never to be finished", and only the owner sets it. Putting DRAFTING, APPROVED and ON-HOLD tasks into DONE makes the dashboard report finished work that doesn't exist. The note is also stored in the PR-URL field, so downstream readers may treat it as a PR. Pre-existing: the PR-field note was already there. The change widens it from IMPLEMENTING-without-PR to every non-DONE state.
Fix: do not route non-IMPLEMENTING states to DONE. Either confirm with the product owner that DONE is intended, or offer an owner-gated ABANDONED move for them.

3. [nit · 3] **`tui/tui_model.py:25`** — the prompt and label hide that the note is stored as the PR
```
ask="note", default=FORCE_NOTE)
```
The old prompt was "note recorded as the PR", and the old default was "none (committed to main)". The new prompt is just "note". The default "closed: stale" is wrong for an IMPLEMENTING task whose work did land on main. The owner can't tell that this is a permanent, irreversible state change recorded in the PR field, and there is no confirmation step.
Fix: keep the "recorded as the PR" wording in `ask`, and make the label say that the task becomes DONE with no PR.