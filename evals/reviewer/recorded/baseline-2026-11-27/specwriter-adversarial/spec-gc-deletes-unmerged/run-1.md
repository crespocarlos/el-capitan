**Critical**

**"Add `crew-task.py gc`, which lists the finished tasks past a retention period and, with `--apply`, deletes them."** — The spec equates "finished" with DONE, but the Summary itself says DONE only requires a PR URL, not that the PR merged. Landing is tracked separately in `crew ls --all` (`yes`/`no`/`unknown`). So `gc --apply` can irreversibly delete the SPEC, PROGRESS and review runs of work that was never merged, or whose merge status is unknown. That is the opposite of safe cleanup, and no criterion covers it.
Fix: Decide whether GC may touch tasks whose `landed` is not `yes`, and add criteria for `no` and `unknown`, including GitHub being unreachable. Put the question under Open questions if it is a user call.

**Acceptance criteria — "last PROGRESS.md line is older than `retention_days`"** — The age rule has several gaps:
- It does not say how the age is read: a timestamp parsed from the line, or the file mtime.
- A missing or empty PROGRESS.md is not handled.
- A line with no parseable timestamp is not handled.
- "Older than" at exactly 30 days is not defined.
- Timezone handling is not specified.

Task 3 tests "the age boundary", but no criterion defines it. A wrong parse could make recent tasks look old and delete them.
Fix: State the age source, the boundary inclusivity, and the behavior for missing or unparseable data. Treat unparseable data as not eligible.

**Important**

**Acceptance criteria — `gc --apply` deletes directories** — Deletion has no safeguards or error handling:
- There is no criterion for a partial failure, such as a permission error midway through the list.
- There is no criterion for a task directory that holds an active worktree or has been modified since listing.
- There is no check that the path stays inside `~/.agent/tasks` (for example a symlink).
- There is no recovery option. The default is dry-run, but the spec never says so.

Fix: Add criteria that dry-run is the default, that failures are reported per task with a non-zero exit code, and that deletion is confined to the tasks root.

**Acceptance criteria — `retention_days` from `~/.agent/config.json`** — The config behavior is unspecified when the file is missing, malformed, or holds a non-integer, zero, or negative value. A value of 0 or a negative would make every DONE task eligible. Task 2 has no matching criterion or test row.
Fix: Add criteria for each invalid-config case, specifying a fallback to 30 or an error, and add test rows for them.

**Tests — Unit only** — The tests never exercise the real `crew-task.py gc` entry point, the `--apply` deletion on a filesystem fixture, or the interaction with `landed` status. `--apply` is the destructive path and its tests are not specified.
Fix: Add an integration block that runs the CLI against a temp tasks directory and asserts what was deleted and what was kept.

Verdict: 4 finding(s), 1 unverified (originating issue; I did not open any case files, so the `mark-done` and `landed` claims are taken from the spec's own text)