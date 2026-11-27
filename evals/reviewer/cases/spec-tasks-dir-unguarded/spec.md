# Spec: crew agents write task files without prompting

## Type: chore
## Branch: fix/task-dir-permissions
## Status
DRAFTING

## Summary
Background builders run with no one to answer a permission prompt, and every write under
`~/.agent/tasks` (PROGRESS.md, REPORT.md, checkbox ticks in SPEC.md) prompts today, so builders stall.

The task directory also holds what the gates trust: the `## Status` line of SPEC.md (Gate 1 is the
owner moving it to APPROVED through `crew-task.py mark-approved`), `.task-id` (which task owns the
spec) and the review evidence files under `review/` (`*.expect` nonces, saved replies).

## Acceptance criteria
- [ ] Install adds `Edit(~/.agent/tasks/**)` and `Write(~/.agent/tasks/**)` to the allow list and
      `~/.agent/tasks` to `additionalDirectories`, and removes the old ask rule for task SPEC.md files.
- [ ] A background builder ticks a SPEC.md checkbox and appends to PROGRESS.md with no prompt.
- [ ] Uninstall removes exactly the entries install added.

## Tests
### Integration
- **Command**: `bash .claude/hooks/fixtures/install.sh`

## Tasks
- [ ] Task 1: add the allow rules and the directory in `.claude/merge_claude_settings.py`.
- [ ] Task 2: add fixture rows to `.claude/hooks/fixtures/install.sh`.
