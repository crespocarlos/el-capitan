Assessment: request-changes — the availability condition `state != "DONE"` also offers "close as done" on ABANDONED tasks (and on unset or unreadable states), which the spec leaves out.

Read beyond the package: `.agent/tools/task/task_status.py`; grep for `force|ABANDONED` (`crew-task.py` is not in the working directory)

Criteria: 2 satisfied, 1 partially satisfied, 1 contradicted, 1 unverified

- Satisfied: a close move is offered for DRAFTING, APPROVED and ON-HOLD.
- Satisfied: it is offered for IMPLEMENTING without a PR.
- Partially satisfied: the owner "types a short note". The prompt is now `ask="note"`, replacing the old `ask="note recorded as the PR"`. The prompt no longer says the note is recorded as the PR URL, and a default is pre-filled.
- Contradicted: the stale-task scope. ABANDONED, empty and unreadable states also get the move.
- Unverified: that the CLI accepts `mark-done --force` from DRAFTING, APPROVED and ON-HOLD. The `GATES` comment says the CLI refuses any state other than IMPLEMENTING for `mark-done`. `crew-task.py` is not in the working directory.

1. [blocking · 4] **`tui/tui_model.py:21`** — "close as done" is offered on ABANDONED tasks
```
if state != "DONE" and not (state == "IMPLEMENTING" and prs):
    found.append(Move("close as done (mark-done --force)", ...
```
ABANDONED is an owner-only side state meaning "dropped, never to be finished". It is not DONE, so this condition offers it the close move. Picking that move on an ABANDONED task would record it as DONE with the default note "closed: stale". That reverses the owner's decision and falsely reports abandoned work as completed. The same condition offers the move for an empty or `None` state (a spec with no status, or an unreadable file).
Fix: Offer the move only from the states named in the spec, for example `state in ("DRAFTING", "APPROVED", "ON-HOLD") or (state == "IMPLEMENTING" and not prs)`.

2. [needs more info · 3] **`tui/tui_model.py:21`** — will the CLI accept `mark-done --force` from DRAFTING, APPROVED and ON-HOLD?
The `GATES` comment says "the CLI refuses any other" state, and `mark-done`'s source state is IMPLEMENTING. If `--force` does not bypass that check, the dashboard offers a move on three of the four target states that the CLI then rejects. The person types a note and gets an error. I could not read `crew-task.py`. Does `--force` skip the source-state check? If not, the move is a dead end for those states.

3. [attention · 3] **`tui/tui_model.py:22`** — the prompt no longer says what the note does
```
ask="note", default=FORCE_NOTE
```
The old prompt was "note recorded as the PR". The note is still passed as the `--pr-url` value, so it lands in the PR field. The label "close as done" and the prompt "note" also hide that the task becomes DONE with no PR.
Fix: restore the wording, for example `ask="note recorded as the PR (closes the task as DONE)"`.