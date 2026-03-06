# Agent Context — el-capitan

## Pipeline & Task State

Defined in the orchestrator rule (`crew-orchestrator.mdc`). Key points:

- Spec-driven: every non-trivial task starts with a SPEC.md before implementation
- Task files live at `~/.agent/tasks/<repo>/<branch>/`
- Done = acceptance criteria pass, not "looks right"
- Resolve repo/branch automatically:
  ```bash
  REPO=$(basename $(git rev-parse --show-toplevel))
  BRANCH=$(git branch --show-current)
  TASK_DIR=~/.agent/tasks/$REPO/$BRANCH
  ```

## Pre-Task Checklist

1. `git status` — working tree clean?
2. `git branch` — correct branch?
3. Read `$TASK_DIR/SPEC.md` if it exists
4. Read `$TASK_DIR/PROGRESS.md` if resuming

## Style Preferences

- TypeScript, const arrow functions, explicit return types
- snake_case filenames, PascalCase components
- No `any`, no `@ts-ignore`
- Single quotes
- `import type` for type-only imports

## Conventions Learned the Hard Way

(This section grows over time from journal entries. Add items here when patterns recur.)
