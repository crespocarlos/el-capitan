---
name: crew-diff-check
description: "Review the current git diff for issues before committing. Use when the user says 'review the diff', 'check my changes', 'ready to commit?', or 'is this good to push'."
---

# Diff Review

## When Invoked

1. Run `git diff` (or `git diff --staged` if there are staged changes)
2. Scan the diff for the following categories:

### Type Safety
- `any` or `unknown` introduced without justification
- Missing return types on exported/public functions
- Non-null assertions (`!`) without local justification
- `@ts-ignore` or `@ts-expect-error` added

### Test Coverage
- New functions or branches without corresponding test changes
- Modified behavior where existing tests don't cover the change
- Removed test assertions

### Pattern Violations
- Naming conventions broken (snake_case files, PascalCase components, camelCase functions)
- `eslint-disable` comments added
- Inline styles where Emotion/EUI should be used
- New dependencies that duplicate existing utilities

### CLAUDE.md Conventions
- Read `~/.claude/CLAUDE.md` for any project-specific conventions
- Flag violations of any listed patterns

## Output Format

Return a short, scannable list. No essays. Each item:

```
[CATEGORY] file:line — one sentence description
```

Example:
```
[TYPE SAFETY] src/services/data.ts:42 — exported function missing return type
[TEST COVERAGE] src/utils/retry.ts:15 — new retry logic has no test
[PATTERN] src/components/Header.tsx:8 — inline style, should use Emotion
```

If the diff looks clean, say so in one sentence.