# Agent Context — el-capitan

## Pipeline & Task State

Defined in the orchestrator rule (`crew-orchestrator.mdc`). Key points:

- Spec-driven: every non-trivial task starts with a SPEC.md before implementation
- Each task lives in its own slug directory: `~/.agent/tasks/<repo>/<branch>/<slug>/`
- Done = acceptance criteria pass, not "looks right"
- Resolve repo/branch, then find the active task:
  ```bash
  REPO=$(basename $(git rev-parse --show-toplevel))
  BRANCH=$(git branch --show-current)
  BRANCH_DIR=~/.agent/tasks/$REPO/$BRANCH
  # TASK_DIR = parent of the active (non-DONE) SPEC.md under $BRANCH_DIR/*/
  # Fall back to $BRANCH_DIR/SPEC.md for old flat layout
  ```

## Pre-Task Checklist

1. `git status` — working tree clean?
2. `git branch` — correct branch?
3. Find the active `TASK_DIR` under `$BRANCH_DIR`
4. Read `$TASK_DIR/SPEC.md` if it exists
5. Read `$TASK_DIR/PROGRESS.md` if resuming

## Style Preferences

- TypeScript, const arrow functions, explicit return types
- snake_case filenames, PascalCase components
- No `any`, no `@ts-ignore`
- Single quotes
- `import type` for type-only imports

## Conventions Learned the Hard Way

- **Explicit handoffs.** Every skill step that hands off to another step must explicitly name the next step and say "proceed immediately." Vague instructions like "monitor output" cause agents to hang waiting for a signal that never comes.
- **Explicit routing only.** All triggers start with `crew`. No natural-language guessing. If the message doesn't start with `crew` (or use `@crew-researcher`), respond normally.
