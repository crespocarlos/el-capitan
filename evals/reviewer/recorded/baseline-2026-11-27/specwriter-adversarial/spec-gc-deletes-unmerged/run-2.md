**Critical**

**"Add `crew-task.py gc`, which lists the finished tasks past a retention period and, with `--apply`, deletes them."** — The spec treats DONE as "safe to delete", but DONE does not mean the PR merged.

The spec's own second paragraph says `mark-done` only requires a PR URL, and that whether the PR merged is shown separately by `crew ls --all` as `landed` (yes, no or unknown). So `gc --apply` would irreversibly delete the SPEC, PROGRESS and review runs for tasks whose PR was closed unmerged, or whose merge state is unknown. That is the likely complaint behind "grows without bound", and the criteria don't address it. "A task in any other state is never listed" also protects only the wrong axis.

Fix: add a criterion for how `landed=no` and `landed=unknown` (including GitHub being unreachable) are handled, for example "only `landed=yes` is eligible". If that is a user decision, put it under `## Open questions` as `[NEEDS CLARIFICATION: …]`.

**Important**

**Criterion 1, "last PROGRESS.md line is older than `retention_days`"** — The age source is ambiguous and the failure cases are missing.

Is age taken from a timestamp inside the last line, or from the file's mtime? What happens when PROGRESS.md is missing, empty or has no parseable timestamp? Is "older than" strictly greater than, or at least? Task 3 promises a boundary test, but the criteria give it nothing to assert. A wrong age call here means a deletion.

Fix: define the age source, the strict or inclusive comparison, and the rule for a task with no usable timestamp (skip, never delete).

**Criterion 2 (`--apply`) / Tasks 1–2** — Nothing is said about deletion safety or partial failure.

There is no criterion for a failed deletion midway through a batch, the exit code, symlinks, or confirming each path resolves inside `~/.agent/tasks`. The spec also doesn't say whether the "worktree notes" in the Summary are inside the task directory or point at a live worktree. A bad path or an unhandled error in an irreversible command is a real risk.

Fix: add criteria for the containment check, continuing past a per-task error and reporting it, and a non-zero exit when any deletion fails.

**Task 2 / `retention_days`** — The config handling has no acceptance criterion.

The spec says nothing about a missing config file, malformed JSON, a missing key, or a zero, negative or non-integer value. It also doesn't say whether `--json` combined with `--apply` prints the deleted paths.

Fix: add criteria for each config case, with invalid values failing loudly rather than falling back to 0, and state what `--json --apply` prints.

**Consider**

**`## Tests` / Unit only** — The tests cover only age, state and `--json`.

There is no case for `landed` values, GitHub being unavailable, or `--apply` actually removing directories. The tests must also run against a temp tasks directory and a temp config, never the real `~/.agent`.

Fix: add test rows for those cases and state that the fixtures are isolated.

Verdict: 5 finding(s), 3 unverified: how `mark-done` and `crew ls --all` behave, the PROGRESS.md line format, and whether worktree notes live inside the task directory. I did not open any case files, so these come from the spec's own text.