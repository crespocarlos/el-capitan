---
name: ae-pr-comments-eval
description: Evaluate and act on code suggestions from any source — GitHub Copilot, code reviewers, colleagues, or AI tools. Use when the user pastes a suggestion alongside code and asks whether to apply it, or says "Copilot says...", "reviewer says...", "someone suggested...", etc.
---

# Code Suggestion Reviewer

## Workflow

1. **Read the target code** — always read the file and surrounding context before deciding.
2. **Classify** — see decision framework below.
3. **Act** — apply, adapt, or reject with a clear one-sentence rationale.
4. **Clean up** — fix lints, remove dead code, update related call sites.

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
- **Wrong mental model** — suggestion misunderstands a contract, invariant, or design intent; explain the actual behavior
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
- If applying: make the edit, then explain what changed and why — no pre-edit narration
- If rejecting: explain the specific reason so the user can push back if they disagree
