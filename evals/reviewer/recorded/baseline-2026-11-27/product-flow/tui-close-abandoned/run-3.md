Assessment: request-changes — the close move is offered on every non-DONE state, including the owner-only ABANDONED state, so a dropped task can be closed as done.

Criteria: 1 satisfied, 1 partially satisfied, 0 contradicted, 1 unverified

- Satisfied: the move is offered for DRAFTING, APPROVED, ON-HOLD and IMPLEMENTING without a PR, and the user types a note.
- Partially satisfied: the move is limited to the stale states. The condition is `state != "DONE"`, so it also covers ABANDONED and unrecognised states.
- Unverified: whether `crew-task.py mark-done --force` accepts the non-IMPLEMENTING states. `GATES` says the CLI refuses any other source state. `crew-task.py` is not in the working directory, so I could not read it.

1. [blocking · 4] **`tui/tui_model.py:21`** — close-as-done is offered on ABANDONED tasks
```python
    if state != "DONE" and not (state == "IMPLEMENTING" and prs):
        found.append(Move("close as done (mark-done --force)", ...
```
`task_status.py` defines ABANDONED as a side state that only the owner sets, meaning "dropped, never to be finished". The `!= "DONE"` test lets it through. A row showing ABANDONED therefore gets "close as done", and one pick plus a note would record the task as DONE. That rewrites a deliberate "dropped" decision into a false "completed". The same test also offers the move for `""` (no status set) and any unrecognised value, and the spec limits the move to four named states.
Fix: allow-list the stale states, e.g. `state in ("DRAFTING", "APPROVED", "ON-HOLD") or (state == "IMPLEMENTING" and not prs)`.

2. [needs more info · 2] **`tui/tui_model.py:22`** — the CLI may refuse the move from DRAFTING, APPROVED and ON-HOLD
The `GATES` comment says each gate moves from one state only and that "the CLI refuses any other". `mark-done` is listed with source IMPLEMENTING. If `--force` does not lift that restriction, the owner picks "close as done", types a note, and gets a CLI error. Question: does `crew-task.py mark-done --force` accept DRAFTING, APPROVED and ON-HOLD? If it doesn't, the move is a dead end for three of the four stale states the ticket names.

3. [nit · 3] **`tui/tui_model.py:4`** — the recorded note is mislabelled and the default hides the owner's reason
The note goes into `--pr-url`, and `FORCE_NOTE` is now "closed: stale" for every close. The move's `ask` prompt changed from "note recorded as the PR" to just "note". The owner is no longer told that the text lands in the PR field, so a typed reason may show up later as a PR link. Fix: restore the explanatory prompt wording.