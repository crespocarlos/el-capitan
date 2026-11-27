Assessment: request-changes — the close move is offered for `ABANDONED` tasks, so a task the owner dropped can be marked DONE from the dashboard.

Read beyond the package: `.agent/tools/task/task_status.py`, plus a grep of the working directory for `ABANDONED`, `force` and `ON-HOLD`.

Criteria: 2 satisfied, 1 partially satisfied, 1 contradicted, 0 unverified. The criteria are the spec's stated ones:
- Close is offered from DRAFTING, APPROVED, ON-HOLD and IMPLEMENTING without a PR: satisfied.
- The owner types a note: satisfied.
- Close is not offered to a task with a PR: satisfied. The move is hidden when IMPLEMENTING has PRs.
- ABANDONED is an owner-only state: contradicted.

The partially satisfied item is the spec's list of source states. The code uses `state != "DONE"` rather than that list, so it offers close for any state outside DONE.

1. [blocking · 4] **`tui/tui_model.py:21`** — close as done is offered for ABANDONED tasks and for any unknown or empty status
```
if state != "DONE" and not (state == "IMPLEMENTING" and prs):
    found.append(Move("close as done (mark-done --force)", ...
```
The spec lists four source states: DRAFTING, APPROVED, ON-HOLD and IMPLEMENTING without a PR. `SIDE_STATES = ("ABANDONED",)` is a state only the owner sets, meaning "dropped, never to be finished". With this condition, any dashboard user who opens an ABANDONED row sees "close as done". Picking it records a dropped task as DONE, with the note "closed: stale" in the PR field. The same applies to an empty or unreadable status, which `read_status` returns as `""` or `None`. The CLI may refuse some of these, but the dashboard still offers an action it may reject. If the CLI accepts `--force` from ABANDONED, the false state is recorded. I could not read the CLI, so that part is unverified.
Fix: allow the move only from the listed states, for example `state in ("DRAFTING", "APPROVED", "ON-HOLD") or (state == "IMPLEMENTING" and not prs)`.

2. [attention · 3] **`tui/tui_model.py:19`** — "blocked" is still offered for ABANDONED tasks
```
if state != "DONE":
    found.append(Move("blocked with a reason (blocked)", ...
```
This was already the case before the change, but the new close move now sits next to it. The owner-only ABANDONED state can still be moved by a dashboard user.
Fix: exclude `SIDE_STATES` from the generic moves, and confirm the CLI's `blocked` behaviour on them.

3. [attention · 3] **`tui/tui_model.py:4`** — the default note "closed: stale" is recorded in the PR URL field
```
FORCE_NOTE = "closed: stale"
```
A task closed by this move, and one that was really finished without a PR, look the same in the record. The old text "none (committed to main)" said the work had landed. The new move also drops the note-prompt wording "note recorded as the PR", so the user is no longer told where the note goes. The note then reads as a PR URL to anything that parses that field. A "stale" close is not completed work, and the prompt does not say so.
Fix: keep the "recorded as the PR" hint in `ask`, for example `ask="note recorded as the PR"`.

4. [nit · 3] **`tui/tui_model.py:24`** — the label "close as done" has no confirmation and no hint that it is a forced close
The move writes DONE for work that may never have been finished. Cost: an accidental keypress on the row records false completion. It can be undone only by hand-editing the spec.