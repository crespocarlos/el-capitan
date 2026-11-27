**Summary / `gc --apply` criterion** — Deletion ignores whether the PR merged

DONE only means `mark-done` got a PR URL, not that the PR merged. A task whose PR was closed unmerged, or whose merge status is `no` or `unknown`, is still listed and deleted by `--apply`. That destroys the SPEC.md, PROGRESS.md and review notes of work that never landed, and nothing can undo it.

Fix: add a criterion that `gc` lists a task only when `landed` is `yes`, and say how `no` and `unknown` are handled. This includes GitHub being unreachable, where the task must not be deleted. Put the question of whether unmerged work should ever be collected under `## Open questions`.

**Criterion 2: "`gc --apply` deletes each listed task directory"** — Deletion has no safety net

The deletion has no confirmation, no dry-run default beyond the flag, no containment check on the path, and no protection for a task that is still in use. A task directory that is a symlink, or has an active worktree or in-flight review run, could be removed or followed. A concurrent `mark-done` or a resumed task could be deleted mid-use.

Fix: add criteria that deletion only touches real directories under `~/.agent/tasks`, does not follow symlinks, skips tasks with active worktrees or runs, and continues past and reports a per-task failure.

**Criterion 1: "last PROGRESS.md line is older than `retention_days`"** — The age rule is undefined for edge cases

A task with a missing or empty PROGRESS.md, or a last line with no parseable timestamp, has no age. The builder could treat it as age 0 (never listed) or as infinitely old (always deleted). Also, `retention_days` of 0, negative or non-numeric, or a missing or malformed `config.json`, is unspecified. The "last line" could also be a note appended later without a date.

Fix: state the timestamp source and format, and require that an undeterminable age means the task is not listed. Also state that an invalid `retention_days` or config is a clear error and not a deletion.

**Criterion 4: "`gc --json` prints the listed paths as a JSON array"** — `--json` combined with `--apply` is undefined

It is unclear whether `gc --json --apply` deletes, and whether the per-deletion lines (criterion 2) are mixed into the JSON output and corrupt it. A script that parses the output would break. An empty result is also unspecified.

Fix: specify the `--json` and `--apply` interaction, require stdout to be valid JSON only, and require `[]` when nothing is listed.

Verdict: 4 finding(s), 0 unverified. I read no case files, so I checked nothing against the codebase. The `landed` column semantics come from the spec text alone.