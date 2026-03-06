# crew-implement

Drive implementation of an approved SPEC.md through its tasks until all acceptance criteria pass.

## Modes

This skill supports two execution modes. Both follow the same protocol: pick the first unchecked task, implement it, run its acceptance check, mark it done, repeat.

- **Ralph mode** — hand off to an external loop tool (`ralph`, `ralph.sh`, or similar) that manages agent sessions, context resets, and task progression.
- **Inline mode** — work through tasks directly in the current Cursor session.

Detection is automatic. The user can override with "implement with ralph" or "implement inline".

## Workflow

### Step 1 — Resolve task state

```bash
REPO=$(basename $(git rev-parse --show-toplevel))
BRANCH=$(git branch --show-current)
TASK_DIR=~/.agent/tasks/$REPO/$BRANCH
```

Read `$TASK_DIR/SPEC.md` and `$TASK_DIR/PROGRESS.md`.

### Step 2 — Gate check

If the SPEC.md status is `DRAFTING`, stop:
> "The spec hasn't been approved yet. Run crew-spec and get approval before implementing."

If the status is already `IMPLEMENTING` and PROGRESS.md has completed tasks, you're resuming — skip to the first unchecked task.

### Step 3 — Update progress

Set PROGRESS.md to:
```
## Status: IMPLEMENTING
## Current: implement
## Next: diff-check
```

### Step 3.5 — Create worktree

If already on a feature branch (not `main` or the default branch), skip this step.

Otherwise, fetch the latest from the default branch and create a worktree branching from it:

```bash
DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $NF}')
git fetch origin "$DEFAULT_BRANCH"

BRANCH_NAME=<type>/<short-description>
WORKTREE_DIR=../$REPO-$(echo $BRANCH_NAME | tr '/' '-')

git worktree add -b "$BRANCH_NAME" "$WORKTREE_DIR" "origin/$DEFAULT_BRANCH"
```

Use a conventional branch prefix based on the SPEC.md type:

| SPEC type | Prefix |
|-----------|--------|
| Feature / enhancement | `feature/` |
| Bug fix | `bugfix/` |
| Refactor | `refactor/` |
| Chore / tooling | `chore/` |
| Docs | `docs/` |

Read the `## Type` field from SPEC.md to pick the prefix. Derive the short description from the issue title or SPEC.md goal (lowercase, hyphen-separated).

After the worktree is created:

1. Update `TASK_DIR` to the new branch path and move `SPEC.md` and `PROGRESS.md` there.
2. `cd` into the worktree directory. All subsequent work happens there.

### Step 4 — Detect mode

```bash
which ralph 2>/dev/null || which ralph.sh 2>/dev/null
```

If found and the user didn't say "implement inline", use ralph mode. Otherwise use inline mode.

### Step 5a — Ralph mode

Hand off to the detected ralph tool with the SPEC.md path and extra instructions to enforce the pipeline boundary:

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
2. If any tasks are unchecked, report which ones and ask the user how to proceed.
3. If all tasks are checked, **proceed immediately to Step 6** — do not wait for further input.

### Step 5b — Inline mode

For each unchecked task in SPEC.md, in order:

1. **Read the task** — understand what to change, which files, and the acceptance check.
2. **Read related code** — open the target files and understand context before editing.
3. **Implement** — make the changes described in the task.
4. **Verify** — run the task's acceptance check command. If it fails, fix and re-run. After 3 failed attempts, stop and ask the user.
5. **Mark done** — check off the task in SPEC.md (`- [x]`).
6. **Update PROGRESS.md** — move the task from "In Progress" to "Done", advance to the next task.

After all tasks pass, run the quality gates from SPEC.md (the commands under "Quality gates"). These are typically scoped lint/typecheck/test commands from the repo's AGENTS.md.

### Step 6 — Wrap up

Update PROGRESS.md:
```
## Status: DIFF_CHECK
## Current: diff-check
## Next: commit
```

Tell the user:
> "All tasks done and quality gates pass. Ready for crew-diff-check."

Append to `$TASK_DIR/SESSION.md`:
```
[TIME] crew-implement: completed N/N tasks, files: <changed files summary>
```

## Rules

- Never skip a task's acceptance check. "Looks right" is not done.
- Never reorder tasks — SPEC.md task order may encode dependencies.
- If a quality gate command is missing from SPEC.md, check the repo's AGENTS.md for the right scoped command before inventing one.
- If implementing in inline mode, keep changes focused per task. Don't batch multiple tasks into one edit pass.
- **Stop after quality gates pass.** Never commit, push, or create a PR. The pipeline is: implement → diff-check → commit → pr-open. Each step requires the user to trigger it.
- Never run `git commit`, `git push`, or `gh pr create`. Those belong to crew-commit and crew-pr-open respectively.
