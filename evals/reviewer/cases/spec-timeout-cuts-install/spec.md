# Spec: tests cannot hang unnoticed

## Type: chore
## Branch: fix/test-timeout
## Status
DRAFTING

## Summary
A hung test ran for 23 minutes before anyone noticed; `evals/test.sh` has no per-test timeout. The suite
holds fast unit rows and a few end-to-end rows: the install and upgrade tests run the real `install.sh`
against a temporary HOME and allow themselves up to 300 s with their own `subprocess` timeouts, since a
cold CI runner is slow.

## Acceptance criteria
- [ ] `evals/test.sh` runs pytest with `pytest-timeout` (pinned like `pytest-xdist`) and a per-test
      timeout of 60 s for every test.
- [ ] A deliberately sleeping fixture fails within the timeout with the test's name in the output.

## Tests
### Unit
- **Command**: `bash evals/test.sh -n auto`

## Tasks
- [ ] Task 1: pin `pytest-timeout` and pass `--timeout 60` in `evals/test.sh`.
- [ ] Task 2: add the sleeping fixture to `evals/tools/test_hang_guards.py`.
