**Critical**

**Acceptance criteria, first criterion ("lists every task whose status is DONE and whose last PROGRESS.md line is older than `retention_days`")**: DONE means a PR was opened, not that it merged, so `gc --apply` can delete unmerged work.
- The Summary says `mark-done` only requires a PR URL, and merge state is a separate `landed` value (`yes`, `no` or `unknown`).
- A task marked DONE whose PR is still open, closed unmerged or abandoned, and idle for 30 days, is listed and deleted. That removes the SPEC.md, PROGRESS.md and worktree notes, which may be the only record of the work.
- The spec says nothing about `landed=no` or `unknown`. `unknown` happens when GitHub is unreachable, which would make an offline run delete everything.

Fix: add criteria that only tasks with `landed=yes` are listed or deleted, and that `no` and `unknown` are never deleted. Also state how a GitHub failure is handled.

**Important**

**Acceptance criteria, second criterion ("`gc --apply` deletes each listed task directory")**: deletion is irreversible, with no safety check at delete time.
- The list and the delete are separate runs, so a task can change state between them. It could be reopened, or its PROGRESS.md could be appended to.
- The directory may also hold an active worktree or uncommitted notes, and nothing says what happens if one task fails to delete (a partial failure).
- Under the literal build, `--apply` deletes whatever the selector returned, including a path that is a symlink or lies outside `~/.agent/tasks`.

Fix: add criteria that `--apply` re-checks eligibility immediately before deleting each task, that it deletes only real directories directly under `~/.agent/tasks`, and that a failed deletion is reported and does not abort the rest.

**Acceptance criteria, first criterion ("whose last PROGRESS.md line is older than `retention_days`")**: "last PROGRESS.md line" is ambiguous as the age signal.
- It assumes every line carries a parseable timestamp.
- A missing or empty PROGRESS.md, a line with no date, or a malformed `retention_days` (0, negative, a string) has no defined outcome.
- A builder could treat a missing timestamp as infinitely old and delete the task.

Fix: define the timestamp source and format. State that a task with no parseable timestamp, or a missing file, is never listed, and that an invalid `retention_days` is an error.

Verdict: 3 finding(s), 1 unverified: the working directory contains only SPEC.md, so the `mark-done` and `landed` behaviour comes from the spec's own text and the code was not checked.