Assessment: request-changes — a mistyped `--status` value gives an empty listing and exit 0, so the owner can't tell a typo from "no tasks in that state".

Read beyond the package: `task_status.py`. `task_state.py` and `print_listing` are not in the working directory, so I could not read them.

Criteria: 1 satisfied, 1 partially satisfied, 0 contradicted, 1 unverified. The spec is a single sentence, so I read it as three criteria:
- Filtering by `--status` works. This is satisfied for valid states.
- The filter is repeatable. This is partially satisfied: the flag repeats, but an invalid value fails silently.
- `--status implementing` lists every IMPLEMENTING task. This is unverified; see findings 2 and 3.

1. [attention · 4] **`.agent/tools/task/ls_data.py:16`** — a mistyped or unknown status gives an empty result and exit 0
```python
wanted = {state.upper() for state in states or []}
return [r for r in rows if not wanted or head(r) in wanted]
```
`crew ls --status implemnting` (a typo), `--status impl`, or `--status done` matches nothing. The output is the same as "no tasks are IMPLEMENTING", and the exit code is 0. The owner is told that nothing is in progress when the filter was invalid, which is a misreported result. `task_status.ACCEPTED` already exists and `token()` already raises `StatusError` for unknown values. The code ignores both, and `--status` has no `choices`.
Fix: validate each `--status` value against `ACCEPTED` after upper-casing. Do it with `parser.error(...)`, which exits 2 and lists the valid states, or with `type=`/`choices=` on the argument. Separately, say "no tasks in state X" when a valid filter matches nothing.

2. [attention · 3] **`.agent/tools/task/ls_data.py:16`** — `head(r)` is called on a `TaskState`, but `head` takes a status string
```python
return [r for r in rows if not wanted or head(r) in wanted]
```
`head(value: str | None)` in `task_status.py` calls `.split()` on its argument. `ls_data.py` imports `head` from `task_state`, which I could not read. If that `head` is the same function, `crew ls --status X` raises AttributeError on any task row. If it is a different `head`, the call may be fine. Either way, the filter shouldn't depend on a helper whose contract I can't see.
Fix: pass the row's status field explicitly, for example `head(r.status)`. Confirm the field name against `TaskState`.

3. [attention · 3] **`.agent/tools/task/crew-ls.py:25`** — the help text promises behaviour the diff doesn't implement, and `--all` is not addressed
```python
help="only tasks in STATE (repeatable); shows stale IMPLEMENTING tasks unfolded")
```
The diff has no code for "stale" or "unfolded" tasks. The help doesn't list the valid states. `--status done` may still be hidden because `print_listing` excludes done specs unless `--all` is passed. I could not read `print_listing` to check, so the owner may get an empty list for a valid filter.
Fix: describe only what the code does and list the valid states, for example `one of DRAFTING, APPROVED, IMPLEMENTING, ON-HOLD, DONE, ABANDONED`. Either make `--status done` imply `--all` or document that it doesn't.