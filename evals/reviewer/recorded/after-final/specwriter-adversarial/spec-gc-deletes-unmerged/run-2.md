**Critical: Acceptance criteria 1–2 ("status is DONE", "`gc --apply` deletes each listed task directory")** — DONE doesn't mean merged, and `gc --apply` permanently deletes with no check on that.

The Summary says `mark-done` only requires the PR's URL, and that merge status is a separate GitHub-derived `landed` value (`yes`, `no` or `unknown`). A task marked DONE with a closed-unmerged or still-open PR, or with `landed=unknown` because GitHub was unreachable, is listed and deleted after 30 days. Its SPEC, PROGRESS and review notes are the only record of unmerged work, and they are gone.

Fix: Add criteria that gc lists and deletes only tasks with `landed=yes`, and never `no` or `unknown`. Put under `## Open questions` whether `landed=no` tasks should ever be collected.

**Critical: missing criterion for `--apply` safety** — nothing says what must stay impossible.

Nothing requires that gc leave directories alone when a deletion would be unsafe. Examples: a path that resolves outside `~/.agent/tasks` (symlink or `..`), a task with a live worktree, or a task directory with uncommitted worktree notes. A literal build runs a recursive delete on whatever path was listed.

Fix: Add criteria that deletion is confined to direct children of `~/.agent/tasks`, that symlinks are not followed, and that a failed deletion is reported without aborting the rest or being counted as deleted.

**Important: Criterion 1 ("last PROGRESS.md line is older than `retention_days`")** — the age source is undefined for common cases.

A DONE task with a missing or empty PROGRESS.md has no last line. A line may have no parseable timestamp. The file's mtime is a different answer from the last line's date. A builder can crash, treat the task as infinitely old and delete it, or skip it.

Fix: State the age source and timestamp format, and say a task with no usable timestamp is never listed.

**Important: Criterion 1 / Task 2 (`retention_days` from `~/.agent/config.json`)** — invalid or missing config is unspecified.

A missing file, malformed JSON, `retention_days: 0`, a negative value or a string. A value of 0 or a negative one makes every DONE task eligible immediately, and `--apply` wipes them all.

Fix: Add a criterion that invalid or non-positive values fail with an error or fall back to 30, and never widen the selection.

**Consider: Criterion 2 / `--apply` flow** — there is no dry-run guarantee.

Criterion 1 implies that plain `gc` is read-only. Since `--apply` is irreversible, a criterion that plain `gc` and `--json` without `--apply` delete nothing would fail if that ever changed. The cost is a regression risk, not a present defect.

Verdict: 5 finding(s), 0 unverified. I read nothing beyond the spec, so I verified nothing against the code. The claims about `mark-done` and `crew ls` rest on the spec's own text.