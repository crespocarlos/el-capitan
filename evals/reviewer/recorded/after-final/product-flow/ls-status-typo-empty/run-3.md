Assessment: request-changes — `select` passes a whole row to `head()`, which takes a status string, and an unknown state silently produces an empty listing.
Read beyond the package: `ls_data.py`, `task_status.py`. A grep of `task_state.py` and `task_report.py` found no matches, so neither was available to read.

Criteria: 0 satisfied, 1 partially satisfied, 0 contradicted, 0 unverified. The only criterion is that `--status STATE` (repeatable) lists just the tasks in that state, for example `--status implementing`.

1. [blocking · 3] **`.agent/tools/task/ls_data.py:17`** — `select` calls `head()` on a whole row, not on its status
```
return [r for r in rows if not wanted or head(r) in wanted]
```
`head(value: str | None)` in `task_status.py` calls `.split()` on its argument. `r` is a `TaskState`, not a string. If `TaskState` has no `.split`, `crew ls --status implementing` crashes with an AttributeError. If `head` returns `""` instead, every filtered listing is empty. The import also comes from `task_state`, while `head` is defined in `task_status.py`, and I could not read `task_state.py` to confirm it re-exports `head`. The unfiltered path skips the `head` call, so only the new flag is affected. Fix: pass the row's status field, for example `head(r.status)`. Import `head` from `task_status`, or confirm that `task_state` re-exports it. Add a test that runs `--status`.

2. [attention · 4] **`.agent/tools/task/ls_data.py:16`** — a mistyped or unknown state looks the same as "no tasks"
```
wanted = {state.upper() for state in states or []}
```
`crew ls --status implemnting` matches nothing, prints an empty listing, and exits 0. In `--json` mode it prints `[]`, which a script reads as "no tasks are implementing". The codebase already treats this case elsewhere: `token()` in `task_status.py` says "a typo fails where it is written". The valid values are `STATES + SIDE_STATES`, which includes ABANDONED. Fix: validate each value with `task_status.token()`, or use argparse `choices`, and exit 2 with the list of accepted states. Also normalise case in one place, so `--status Done` and `--status done` behave alike.

3. [attention · 3] **`.agent/tools/task/crew-ls.py:25`** — the help text promises behaviour the diff does not implement, and the interaction with `--all` is unclear
```
help="only tasks in STATE (repeatable); shows stale IMPLEMENTING tasks unfolded"
```
Nothing in the diff folds or unfolds stale rows. The sentence tells the operator that something is hidden without `--status`, and it does not say what "stale" or "unfolded" means. `--all` says "list done specs too", which suggests DONE rows are hidden by default. If `print_listing` still drops DONE rows without `--all`, then `--status done` prints nothing. The operator gets an empty result with no hint to add `--all`. I could not read `task_report.py` to check this. Fix: drop or explain the "unfolded" clause, list the accepted states in the help, and either make `--status done` imply `--all` or print a hint when the filter yields nothing because of `--all`.