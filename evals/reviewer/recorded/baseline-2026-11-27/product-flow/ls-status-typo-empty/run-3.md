Assessment: request-changes — a mistyped `--status` value, such as `--status implementng`, silently returns an empty listing that looks the same as "no tasks in that state".

1. [attention · 4] **`.agent/tools/task/ls_data.py:16`** — an unknown status value produces an empty listing with no explanation
```python
wanted = {state.upper() for state in states or []}
return [r for r in rows if not wanted or head(r) in wanted]
```
The owner runs `crew ls --status implementng` or `--status done-ish`. Nothing validates the value against `ACCEPTED` in `task_status.py`, which already defines the valid set and a `StatusError` message. The command returns an empty table and exit 0. The owner can't tell whether no task is in that state or whether they mistyped. The `ls` reader is meant to stay lenient about malformed task data, but this is user input, not task data. The sibling `token()` makes the same distinction: "a typo fails where it is written".
Fix: validate each requested state in `crew-ls.py` with `parser.error(...)`, using `choices=ACCEPTED` with a case-insensitive `type=str.upper`. The error then lists the valid states. Also print a "no tasks in STATE" line when a valid filter matches nothing.

2. [needs more info · 3] **`.agent/tools/task/ls_data.py:17`** — `head(r)` is given a whole row, not a status string
`head` in `task_status.py:14` takes `str | None` and calls `.split()` on it. `r` is a `TaskState`, and I could not read `task_state.py` (it isn't in the working directory) to see whether `TaskState` is a `str` or exposes `.status`. If it is not a string, every `--status` call raises `AttributeError`, and the feature never works. Question: what does `TaskState` look like, and is there a test that filters on a real row? If `head(r)` is wrong, the feature is broken for everyone who uses it.

3. [needs more info · 2] **`.agent/tools/task/crew-ls.py:32`** — `--status DONE` may be hidden by the default `--all` behaviour
`select` runs before `print_listing`, which per the docstring only lists done specs with `--all`. If `print_listing` still drops DONE rows, `crew ls --status DONE` prints nothing unless the owner also adds `--all`. That is the same silent-empty result as finding 1, on a valid state. Question: does `print_listing` filter DONE after `select`? If so, passing `--status DONE` should imply `--all`.

4. [nit · 3] **`.agent/tools/task/crew-ls.py:25`** — help text promises behaviour the change does not implement
`"shows stale IMPLEMENTING tasks unfolded"` describes no code in this diff, and `--help` doesn't list the valid states. The owner may expect special stale handling, or look for a state name and not find it. Fix: reword to `"only tasks in STATE (repeatable): DRAFTING, APPROVED, IMPLEMENTING, ON-HOLD, DONE, ABANDONED"`.