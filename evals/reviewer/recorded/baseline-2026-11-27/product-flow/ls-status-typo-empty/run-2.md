Assessment: request-changes — a mistyped `--status` value silently produces an empty listing, and I couldn't confirm the filter runs at all.

1. [attention · 4] **`.agent/tools/task/ls_data.py:16`** — unknown `--status` value silently yields an empty listing
```python
wanted = {state.upper() for state in states or []}
return [r for r in rows if not wanted or head(r) in wanted]
```
`--status implmenting` or `--status done-ish` matches nothing, so the person sees an empty listing. That looks the same as "no tasks in that state", so they can't tell a typo from a real result. `task_status.py` already defines `ACCEPTED` and the `StatusError` message that lists the valid states. The `token()` docstring says a typo should fail where it is written. The existing reader is lenient on purpose, but this is user input, not stored data.
Fix: validate in `crew-ls.py` with `choices=ACCEPTED` (or a case-insensitive `type=`), so argparse rejects the value and prints the valid states. Alternatively, print a "no tasks in STATE" note on stderr when the result is empty.

2. [needs more info · 3] **`.agent/tools/task/ls_data.py:17`** — `head(r)` is called on a `TaskState`, and `head` may not be importable from `task_state`
```python
from task_state import TaskState, head, load

...
head(r) in wanted
```
`head(value: str | None)` is defined in `task_status.py` and calls `.split()` on its argument. `ls_data.py` imports it from `task_state`, which isn't in the working directory, so I couldn't check that it re-exports a compatible `head`. Even if it does, passing a whole row would raise `AttributeError` unless `TaskState` is str-like. If either is wrong, `crew ls --status X` crashes for everyone who uses the flag. Is there a `head(TaskState)` in `task_state`, or should this be `head(r.status)`? If it's wrong, the flag is unusable.

3. [attention · 3] **`.agent/tools/task/crew-ls.py:25`** — the help text promises a behavior the code doesn't implement
```python
help = "only tasks in STATE (repeatable); shows stale IMPLEMENTING tasks unfolded"
```
Nothing in the diff handles "stale" or "unfolded" rows. A grep of the task directory found no fold or stale logic, and I didn't read `print_listing`. A person who reads this help expects stale tasks to be shown specially. Separately, `--all` says it "adds done specs". It's unclear whether `--status DONE` shows anything without `--all`. If `print_listing` still hides done specs, the filter returns an empty list with no explanation.
Fix: remove the "stale…unfolded" clause, or implement it. Also decide whether `--status DONE` should imply `--all`, and document the answer in the help text.

Criteria: no spec or ticket was provided; the only stated goal is that `--status implementing` lists every IMPLEMENTING task. I count it unverified, because of finding 2.