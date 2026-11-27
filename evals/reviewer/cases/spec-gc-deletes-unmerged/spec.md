# Spec: garbage-collect finished tasks

## Type: feature
## Branch: feat/task-gc
## Status
DRAFTING

## Summary
`~/.agent/tasks` grows without bound: a busy month leaves sixty task directories, each with its
SPEC.md, PROGRESS.md, review runs and worktree notes. Add `crew-task.py gc`, which lists the finished
tasks past a retention period and, with `--apply`, deletes them.

A task reaches DONE through `crew-task.py mark-done`, which requires the URL of the PR the task
opened. Whether that PR merged is shown by `crew ls --all` in its `landed` column (`yes`, `no` or
`unknown`), read from GitHub.

## Acceptance criteria
- [ ] `gc` lists every task whose status is DONE and whose last PROGRESS.md line is older than
      `retention_days` (default 30, from `~/.agent/config.json`).
- [ ] `gc --apply` deletes each listed task directory and prints one line per deletion.
- [ ] A task in any other state is never listed, whatever its age.
- [ ] `gc --json` prints the listed paths as a JSON array.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_task_gc.py`

## Tasks
- [ ] Task 1: add `.agent/tools/task/task_gc.py` (select, list, apply) and the `gc` subcommand.
- [ ] Task 2: read `retention_days` from `~/.agent/config.json`, defaulting to 30.
- [ ] Task 3: add `evals/tools/test_task_gc.py` with rows for the age boundary, other states and `--json`.
