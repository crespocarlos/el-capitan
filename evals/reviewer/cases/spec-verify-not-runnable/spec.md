# Spec: open the PR from crew-task

## Type: feature
## Branch: feat/open-pr
## Status
DRAFTING

## Summary
Opening a PR is four manual steps. Add `crew-task.py open-pr <TASK_DIR>`: push the branch and open a draft
PR with `gh`, then record it on the task.

## Acceptance criteria
- [ ] `open-pr` pushes the task's branch and opens a draft PR against the base branch.
- [ ] The PR URL is appended to the task's PR list.
- [ ] Re-running it on a task whose PR is open prints the existing URL and opens nothing.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_open_pr.py`

## Tasks
- [ ] Task 1: add `.agent/tools/task/task_open_pr.py` and the `open-pr` subcommand in `crew-task.py`.
- [ ] Task 2: add `evals/tools/test_open_pr.py` with rows for the happy path and the re-run.
- [ ] Task 3: check it end to end. Verify: run `crew-task.py open-pr` on a scratch task in this repository,
      confirm the draft PR appears on github.com, then close it by hand.
