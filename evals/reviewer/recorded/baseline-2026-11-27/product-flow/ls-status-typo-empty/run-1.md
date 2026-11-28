Assessment: request-changes — `--status` with a typo or an unlisted state returns an empty listing with no explanation, so the owner can't tell "no such tasks" from "I mistyped".

1. [attention · 4] **`.agent/tools/task/ls_data.py:16-17`** — an unknown `--status` value silently produces an empty listing
```python
wanted = {state.upper() for state in states or []}
return [r for r in rows if not wanted or head(r) in wanted]
```
`crew ls --status implemeting` filters on a value no task can hold, so the owner sees an empty table or `[]`. That looks the same as "no tasks are implementing", and the owner may wrongly conclude nothing is in flight. `task_status.py` already defines `ACCEPTED` and `StatusError`, which say what a valid state is. The listing's leniency is meant for malformed task data, not for the user's own input. A valid state with zero matches also gets no message, but that is a smaller gap.
Fix: validate each `--status` value against `ACCEPTED` in `crew-ls.py` (for example with argparse `choices` or a case-insensitive check). Fail with a message that lists the valid states. Exit non-zero, and keep stdout clean for `--json`.

2. [needs more info · 3] **`.agent/tools/task/ls_data.py:17`** — `head(r)` may be called on a row, not on a status string
```python
return [r for r in rows if not wanted or head(r) in wanted]
```
`task_status.head` takes a status string (`value.split()`). Here it receives a `TaskState` row, and `task_state.py` isn't in the package. If `TaskState` is not a `str`, every `--status` call raises `AttributeError`. That would break the flag's main use. Also, `head` is imported from `task_state`, but it is defined in `task_status`. Is `head` re-exported from `task_state`, and does it accept a row? If not, the filter crashes for everyone.

3. [attention · 3] **`.agent/tools/task/crew-ls.py:25`** — help text promises behavior the code doesn't implement, and the `--all` interaction is unclear
```python
help = "only tasks in STATE (repeatable); shows stale IMPLEMENTING tasks unfolded"
```
The diff has no "stale" or "unfolded" logic, so the help text describes something the change doesn't do. `--status done` also depends on `--all`, which `select` doesn't consult. Whether `print_listing` hides DONE rows without `--all` can't be seen from the package. If it does, `crew ls --status done` may print nothing with no hint to add `--all`.
Fix: drop or correct the "stale … unfolded" clause. Make `--status done` imply showing done specs, or tell the owner to add `--all`.

Criteria: no spec or ticket in context. The one stated goal, filtering by `--status STATE` (repeatable), is satisfied on the happy path (unverified, per finding 2).