**Critical**

**"Add `crew-task.py gc`, which lists the finished tasks past a retention period and, with `--apply`, deletes them."** — DONE doesn't mean the work landed, and `--apply` deletes permanently.

The Summary says `mark-done` only requires the PR URL, not that the PR merged. The `landed` column (`yes`/`no`/`unknown`) exists because DONE and merged are different things. A task with an unmerged or closed PR, or an `unknown` landing, would have its SPEC, PROGRESS and review notes deleted for good. No criterion mentions `landed`.

Fix: put this under Open questions as `[NEEDS CLARIFICATION: delete only tasks with landed=yes, or also no/unknown?]`. Add criteria for each `landed` value, including what happens when GitHub can't be reached.

**Important**

**Acceptance criterion 2: "`gc --apply` deletes each listed task directory"** — deletion has no safeguards and no failure handling.

The directory also holds worktree notes. The spec doesn't say what happens if a worktree is still live or the directory is still referenced. It doesn't cover a partial failure, such as a permissions error halfway through the list, or a task that changes state between listing and deleting. There's no confirmation, no trash or archive step, and no dry-run guarantee that the default makes no changes.

Fix: add criteria that the default run changes nothing, that a failed deletion is reported and doesn't stop the remaining ones, and that state is re-checked immediately before each delete.

**Acceptance criterion 1: "last PROGRESS.md line is older than `retention_days`"** — the age definition is ambiguous and has unhandled edge cases.

The spec doesn't say how the timestamp is parsed, or what happens if PROGRESS.md is missing, empty, or has a last line with no parseable date. It doesn't say whether the file mtime is a fallback, or whether "older than" is strict. It also doesn't say how an invalid `retention_days` (0, negative, non-integer) or a missing config file is handled. Each of these either deletes the wrong tasks or crashes.

Fix: specify the timestamp source, the strict or inclusive comparison, a rule for unparseable or missing data (skip and warn, never delete), and validation of `retention_days`.

**Tests**

**`## Tests` / Task 3** — the tests don't cover the dangerous paths.

Task 3 lists rows for the age boundary, other states and `--json`. It has none for `--apply`'s actual deletion, for `landed` values, or for missing or malformed PROGRESS.md. An `--apply` test must also run against a temp directory so it can't touch the real `~/.agent/tasks`.

Fix: add criteria for the `--apply` deletion test, the unmerged and unknown cases, and the malformed-input cases, and require a sandboxed home directory.

Verdict: 4 finding(s), 3 unverified. I did not verify that `crew ls --all` and `landed` exist as described, the PROGRESS.md line format, or the `mark-done` behavior. I used no tool calls.