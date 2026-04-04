---
name: crew-diff
description: "Review the current git diff for issues before committing. Trigger: 'crew diff'."
---
**Workflow**: build | **Stage**: diff

# Diff Review

## Execution model

**Single-shot output.** Load context, run diff, scan all categories without intermediate output. Only speak once — when all findings are ready.

Target: 1 turn.
- Turn 1: auto-recall + diff scan + full findings

Never narrate what you're scanning. Never say "now checking type safety".

## When Invoked

### Step 1: Load context

Load repo-specific patterns:

```bash
REPO=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "unknown")
~/.agent/tools/journal-search.py auto-recall "$REPO" --top 3 2>/dev/null || true
```

Resolve TASK_DIR for progress logging:

```bash
TASK_DIR=$(~/.agent/tools/resolve-task-dir.sh) || exit 1
```

Add any recalled rules to the pattern violations checklist below. For example, if a recalled pattern says "always use data-test-subj for test selectors", flag new components missing them.

### Step 2: Scan the diff

1. Run `git diff` (or `git diff --staged` if there are staged changes)
2. Scan the diff for the following categories:

### Step 3: Type safety
- `any` or `unknown` introduced without justification
- Missing return types on exported/public functions
- Non-null assertions (`!`) without local justification
- `@ts-ignore` or `@ts-expect-error` added

### Step 4: Test coverage
- New functions or branches without corresponding test changes
- Modified behavior where existing tests don't cover the change
- Removed test assertions

### Step 5: Pattern violations
- Naming conventions broken (snake_case files, PascalCase components, camelCase functions)
- `eslint-disable` comments added
- Inline styles where Emotion/EUI should be used
- New dependencies that duplicate existing utilities

### Step 6: Recalled patterns + CLAUDE.md
- Check recalled patterns from auto-recall (above) — these are repo-specific rules from the journal
- Read `~/.claude/CLAUDE.md` for any global conventions
- Flag violations of any listed patterns from either source

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

## Progress

After reporting findings, append to `$TASK_DIR/PROGRESS.md` (TASK_DIR resolved above):

```bash
# If issues found:
~/.agent/tools/log-progress.sh "$TASK_DIR" "DIFF_CHECK: issues found — pending fixes"
# If clean:
~/.agent/tools/log-progress.sh "$TASK_DIR" "DIFF_CHECK → COMMITTING"
```
## Classification

Based on findings above, determine verdict:
- **PASS**: no issues found
- **WARN**: issues found but none require fixing before commit (style, suggestions, minor improvements)
- **BLOCK**: at least one issue that must be addressed before committing (bug, security flaw, missing required change)

Output: `Verdict: PASS` / `Verdict: WARN` / `Verdict: BLOCK`

**Conclusion:**
- If PASS or WARN: "Run `crew commit` to proceed."

> Next: run `crew commit` to continue.
- If BLOCK: "Address the issues above before committing."
