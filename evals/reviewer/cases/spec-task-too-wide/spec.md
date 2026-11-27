# Spec: notify when a background job goes idle

## Type: feature
## Branch: feat/idle-notify
## Status
DRAFTING

## Summary
The owner misses background jobs that finish or wait for input. Show a desktop notification when a job
goes idle, at most once a minute, with an off switch.

## Acceptance criteria
- [ ] An idle job shows one notification naming the job; a second within 60 s shows nothing.
- [ ] `EL_CAPITAN_NOTIFY=0` turns it off.
- [ ] The hook never blocks the session: it exits 0 on every path.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_hook_cases.py`

## Tasks
- [ ] Task 1: add the rate-limit stamp helper to `.claude/hooks/lib/hook.sh`.
- [ ] Task 2: write `.claude/hooks/notify-idle.sh`, register it in `.claude/settings.json` and
      `.cursor/hooks.template.json`, add its install entry to `.claude/merge_claude_settings.py`, document it in
      `docs/hooks.md` and `README.md`, and add its rows to `evals/tools/hook_cases.py`.
- [ ] Task 3: add the off switch to `docs/hooks.md`.
