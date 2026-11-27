Assessment: request-changes — the close move is offered on ABANDONED tasks, and for the owner-only state that is the wrong outcome. It is also offered on any unreadable or unset status.
Read beyond the package: `.agent/tools/task/task_status.py`

Criteria: 3 satisfied, 0 partially satisfied, 1 contradicted, 0 unverified
- Satisfied: DRAFTING, APPROVED and ON-HOLD get the move.
- Satisfied: IMPLEMENTING without a PR gets the move.
- Satisfied: the owner types a note.
- Contradicted: "stale tasks: DRAFTING, APPROVED, ON-HOLD, or IMPLEMENTING without a PR". ABANDONED and any other status also get the move.

1. [blocking · 4] **`tui/tui_model.py:22`** (h1) — "close as done" is offered on ABANDONED tasks, and on unset or unreadable statuses
```
if state != "DONE" and not (state == "IMPLEMENTING" and prs):
    found.append(Move("close as done (mark-done --force)", ...
```
The condition is a negative, so every state other than DONE satisfies it. That includes ABANDONED, which `task_status.py` defines as a user-only side state meaning "dropped, never to be finished". It also includes `""` (status unset) and whatever the TUI passes when `read_status` returns None. An operator who selects an abandoned task sees "close as done", types a note, and the task is recorded DONE with "closed: stale" as its PR. The owner's decision to drop the task is overwritten, and the dashboard now says it was finished. If the CLI refuses the call, the operator is offered an action that then fails. The `blocked` move has the same loose condition, but that is pre-existing and not part of this change.

Fix: allow-list the states the spec names, e.g. `if state in ("DRAFTING", "APPROVED", "ON-HOLD") or (state == "IMPLEMENTING" and not prs):`. Do the same for the new move only.

2. [attention · 3] **`tui/tui_model.py:4`** — the default note says "stale" for every close, and it is recorded in the PR-URL field
```
FORCE_NOTE = "closed: stale"  # the `--pr-url` note of the close move
```
The move is offered for DRAFTING or APPROVED tasks that were never implemented. If the operator presses Enter on the default, the record says "closed: stale" where a PR link would normally be. Because `--pr-url` is also read as a link, consumers of that field may treat the note as a URL. The prompt also changed from "note recorded as the PR" to a bare "note", so the operator no longer sees where the text goes.

Fix: keep the prompt text saying the note is recorded as the PR/closure note. Consider requiring a typed note rather than pre-filling a default that claims a reason.