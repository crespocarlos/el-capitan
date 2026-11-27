# Spec: close any stale task as done

## Type: feature
## Branch: feat/close-stale
## Status
DRAFTING

## Summary
Stale tasks clutter `crew ls`: specs that were drafted and never approved, approved work that was
dropped, and tasks implemented with no PR. Today `crew-task.py mark-done --force` only works from
IMPLEMENTING. Let the owner close any of them as done, from the CLI and from the TUI.

Gate 1 (`mark-approved`) is the owner's approval of a spec; only an APPROVED spec may be implemented,
and a DONE task with a PR is read as shipped, approved work. ABANDONED is a side state only the owner
sets.

## Acceptance criteria
- [ ] `mark-done --force --pr-url <value>` closes a task in any state but DONE as DONE. The value is
      logged in PROGRESS.md as the reason; a GitHub PR URL is also added to the task's PR list.
- [ ] The TUI offers "close as done" on every row that is not DONE, with a note prompt.
- [ ] A forced close ends an open BLOCKED line.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_lifecycle.py`

## Tasks
- [ ] Task 1: relax the state check in `.agent/tools/task/task_gates.py` `mark_done` under `--force`.
- [ ] Task 2: add the close move to `tui/tui_model.py` `moves`.
- [ ] Task 3: add rows to `evals/tools/test_lifecycle.py` and `evals/tools/test_tui_model.py`.
