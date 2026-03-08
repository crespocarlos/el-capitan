---
name: crew-eval-pr-comments
description: "Evaluate and act on code suggestions from any source. Trigger: 'crew eval: <suggestion>'."
---

# Code Suggestion Reviewer

## Step 0 — Resolve worktree

If the suggestion references a PR or branch, resolve to the correct working directory:

```bash
BRANCH=<branch from PR or context>
cd "$(resolve-worktree "$BRANCH")"
```

If no branch context is provided (standalone suggestion), skip this step and work in the current directory.

## Auto-recall

```bash
REPO=$(basename $(git rev-parse --show-toplevel) 2>/dev/null || echo "unknown")
journal-search auto-recall "$REPO" --top 3 2>/dev/null || true
```

Apply any recalled rules silently during evaluation. If a recalled pattern conflicts with the suggestion, factor it into the verdict.

## Workflow

1. **Read the target code** — always read the file and surrounding context before deciding.
2. **Read the tests** — if the target code has tests, read them before evaluating. Tests that explicitly validate the flagged behavior (with comments explaining the design, probability model, or intent) are strong evidence the behavior is intentional, not a bug.
3. **Classify** — see decision framework below.
4. **Act** — apply, adapt, or reject with a clear one-sentence rationale.
5. **Clean up** — fix lints, remove dead code, update related call sites.

## Decision Framework

### Apply
- Real logic bug: wrong semantics, silent data loss, incorrect default, off-by-one
- Missing edge case that callers can realistically hit
- Type unsafety that could surface as a runtime error
- Correctness issue that the suggestion accurately diagnoses and fixes

### Adapt
Correct diagnosis, needs a different remedy:
- Fix exists but should use existing codebase patterns/utilities instead of introducing new ones
- Suggestion is correct but verbose — apply then simplify
- Suggestion introduces an abstraction when an inline change suffices
- Suggestion duplicates an existing utility — use the existing one

### Reject
- **Premature optimization** — actual data is small/bounded; theoretical complexity concern has no measurable impact
- **Wrong mental model** — suggestion misunderstands a contract, invariant, or design intent; explain the actual behavior. Common pattern: reviewer flags behavior as a bug when the test suite explicitly validates it as intentional
- **Defeats the purpose** — suggested change undermines the intent of the code it modifies
- **Duplicate** — already addressed earlier in the same session
- **Out of scope** — correct but requires a framework-level refactor unrelated to the current change

### Defer
Correct and worth doing, but out of scope for the current change — note it and move on.

## After Applying

- Run lints on edited files only; fix any introduced errors
- Run type-check scoped to the affected package/tsconfig, not the whole repo
- Search for other call sites with the same bug and fix them before closing
- If the fix introduces a reusable pattern, extract a helper
- Delete dead code, unused imports, and types that result from the change

## Communication Style

- State the verdict first: **Apply**, **Adapt**, **Reject**, or **Defer**
- One sentence explaining why
- If rejecting: explain the specific reason so the user can push back if they disagree

### User gate — mandatory

**Never apply, reject, or adapt a suggestion without presenting it to the user first.** Show:
1. The verdict and rationale
2. The proposed code change (if applying/adapting)
3. The proposed GitHub reply (if one will be posted)

Wait for the user to approve, modify, or override before proceeding. The user may disagree with your classification — that's expected.

### GitHub comment format

**Never post a reply on GitHub without explicit user approval.** When approved, prefix with a robot indicator so agent comments are distinguishable from human ones:

```
🤖 **Reject** — [rationale]
```

```
🤖 **Apply** — [what changed and why]
```
