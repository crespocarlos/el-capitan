# Agent Context — el-capitan

## How I Work

- Spec-driven: every task starts with a SPEC.md before implementation
- Done = acceptance criteria commands all exit 0, not "looks right"
- Implementation loops use Ralph Loop CLI when available
- Task files live at `~/.agent/tasks/<repo>/<branch>/`

## Pre-Task Checklist

Before starting any task:
1. `git status` — working tree clean?
2. `git branch` — correct branch?
3. Read `~/.agent/tasks/<repo>/<branch>/SPEC.md` if it exists
4. Read `~/.agent/tasks/<repo>/<branch>/PROGRESS.md` if resuming

Resolve repo and branch automatically:
```bash
REPO=$(basename $(git rev-parse --show-toplevel))
BRANCH=$(git branch --show-current)
TASK_DIR=~/.agent/tasks/$REPO/$BRANCH
```

## PROGRESS.md Convention

Update `~/.agent/tasks/<repo>/<branch>/PROGRESS.md` after every meaningful step:
- `Status`: DRAFTING | APPROVED | IMPLEMENTING | REVIEW | COMMITTING | PUSHING | PR_COMMENTS | DONE
- `Phase`: spec → implement → diff-review → commit → push → pr-comments → done
- `Current`: which phase you're in now
- `Next`: which phase comes after

## Spec Template

Copy from `~/.agent/_SPEC_TEMPLATE.md` when drafting a new spec.

## Journal

Append entries to `~/.agent/JOURNAL.md` when asked to log a session.

## Style Preferences

- TypeScript, const arrow functions, explicit return types
- snake_case filenames, PascalCase components
- No `any`, no `@ts-ignore`
- Single quotes
- `import type` for type-only imports

## Conventions Learned the Hard Way

(This section grows over time from journal entries. Add items here when patterns recur.)
