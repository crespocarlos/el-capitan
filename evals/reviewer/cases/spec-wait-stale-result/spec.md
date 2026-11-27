# Spec: run verification in the background and wait for it

## Type: feature
## Branch: feat/verify-background
## Status
DRAFTING

## Summary
A builder runs `crew-task.py verify` and blocks for the whole run, often several minutes, while it
could be writing the report. Add `--background`, which starts the run and returns at once, and
`--wait <path>`, which blocks until the run is finished and prints its verdict. The report check
(`report-check --gates`) reads the same result file, so the report states the gates that really ran.

The result file is `<TASK_DIR>/gates.json` by default (`--out` overrides it). A task runs verify many
times: after each batch, after a fix, and before the PR.

## Acceptance criteria
- [ ] `verify --background` starts the gates in a child process and exits 0 at once, printing the
      result path.
- [ ] The child writes the result file after each gate: `{"state": "running", "gates": [...]}`, then
      `{"state": "done", "verdict": "pass" | "fail", "gates": [...]}` when the last gate finishes.
- [ ] `verify --wait <path>` polls the file every 2 s until its `state` is `done`, prints one line per
      gate, and exits 0 on pass, 1 on fail, 3 after `--timeout` (default 900 s).
- [ ] `report-check --gates <path>` fails a report that claims a gate the file does not list as passed.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_task_verify.py`
- A background run in a fresh task directory, waited on, returns the child's verdict.

## Tasks
- [ ] Task 1: add `background` and `wait` to `.agent/tools/task/task_verify.py`, and the two flags.
- [ ] Task 2: write the result after each gate in `run_all`.
- [ ] Task 3: add rows to `evals/tools/test_task_verify.py`.
