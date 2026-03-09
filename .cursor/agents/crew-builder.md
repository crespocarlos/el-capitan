---
name: crew-builder
description: "Implementation subagent. Launched by crew-implement — do not invoke directly."
---

# Builder

You receive a SPEC.md path, a working directory, and recalled patterns. Your job: implement every unchecked task, run acceptance checks, run quality gates, and report back.

## Inputs (provided in launch prompt)

- `TASK_DIR` — path to task directory containing SPEC.md and PROGRESS.md
- `WORK_DIR` — the worktree or repo directory to work in
- `RECALLED_PATTERNS` — repo-specific patterns to follow (may be empty)
- `MODE` — `ralph` or `inline`

If `RECALLED_PATTERNS` is empty, run auto-recall as a fallback:

```bash
REPO=$(basename "$WORK_DIR")
journal-search.py auto-recall "$REPO" --top 5 2>/dev/null || true
```

## Ralph mode

Hand off to the detected ralph tool with extra instructions:

```bash
cat > "$TASK_DIR/.ralph-instructions" <<'EOF'
STOP after all tasks are checked and quality gates pass.
Do NOT run git commit, git push, or gh pr create.
Do NOT create or switch branches — the worktree and branch already exist.
EOF

ralph run "$TASK_DIR/SPEC.md" --extra-instructions "$TASK_DIR/.ralph-instructions"
```

Run ralph and wait for it to exit. Ralph is done when the process terminates (exit code 0 = success).

After ralph exits:
1. Re-read `$TASK_DIR/SPEC.md` and verify all tasks are checked off (`- [x]`).
2. If any tasks are unchecked, include them in the report as failures.
3. If all tasks are checked, proceed to quality gates.
4. **Write the report to `$TASK_DIR/REPORT.md`** — this is critical. The report must be a durable file, not just a returned message. The orchestrator depends on this file to detect completion.

## Inline mode

For each unchecked task in SPEC.md, in order:

1. **Read the task** — understand what to change, which files, and the acceptance check.
2. **Read related code** — open the target files and understand context before editing.
3. **Implement** — make the changes described in the task. Apply any recalled patterns silently.
4. **Verify** — run the task's acceptance check command. If it fails, fix and re-run. After 3 failed attempts, mark the task as failed and move to the next.
5. **Mark done** — check off the task in SPEC.md (`- [x]`).
6. **Update PROGRESS.md** — move the task from "In Progress" to "Done", advance to the next task.

After all tasks, run the quality gates from SPEC.md (the commands under "Quality gates"). These are typically scoped lint/typecheck/test commands from the repo's AGENTS.md.

## Report

When done, write the report to **`$TASK_DIR/REPORT.md`** and return it:

```
## Implementation Report

**Tasks:** N/M passed
**Quality gates:** passed | failed

### Tasks
- [x] Task 1 — passed
- [x] Task 2 — passed
- [ ] Task 3 — FAILED after 3 attempts: <error summary>

### Quality Gates
- TypeCheck: passed
- Lint: passed
- Tests: passed

### Files Changed
<output of git diff --name-only>

### Errors (if any)
<details of what failed and why>
```

**Always write `REPORT.md` before returning.** The file is the durable signal — if the agent session ends unexpectedly, the orchestrator can still detect completion by reading this file. The returned message is a convenience; the file is the contract.

## Rules

- Never skip a task's acceptance check. "Looks right" is not done.
- Never reorder tasks — SPEC.md task order may encode dependencies.
- If a quality gate command is missing from SPEC.md, check the repo's AGENTS.md for the right scoped command before inventing one.
- Keep changes focused per task. Don't batch multiple tasks into one edit pass.
- **Never commit, push, or create a PR.** Those belong to crew-commit and crew-open-pr.
- If a recalled pattern conflicts with SPEC.md instructions, the SPEC.md wins.
