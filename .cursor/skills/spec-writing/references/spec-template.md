# Spec: [title]

## Type: [feature | bugfix | refactor | chore | docs]
## Branch: [type/short-description — e.g. feat/sigevents-verdict-rename]
## Status
DRAFTING

## Summary
[1-2 paragraphs: what this changes and why. Problem, scope, and goal in prose. Link to issue/PR if
applicable.]

Out of scope: [adjacent work a reader might expect — one-phrase reason each]

## Open questions
- [NEEDS CLARIFICATION: question — what breaks if guessed wrong] [Delete this section when empty. A
  spec with open items cannot be approved.]

## Acceptance criteria
- [ ] WHEN [trigger or input] THEN [observable outcome] — verify: `[command]`
- [ ] [Structural constraint: boundary, API surface, or pattern] — verify: inspect `[path]` for
  [what]
- [ ] Non-regression: [existing behavior X preserved] — verify: `[command]`

## Tests
[Keep only the layers that apply. Each kept layer needs a runnable command.]
### Unit
- **Command**: `[command]`
### Integration
- **Command**: `[command]`
### E2E
- **Command**: `[command]`
### Validation
- **Command**: `[lint, type-check, or other quality gate]`

## Tasks
- [ ] 1) [Task name]
  - [What to change, which files. 1-3 sentences.]
  - Verify: `[command]` or "inspect: [what to check]"

- [ ] 2) [Task name]
  - [What to change, which files.]
  - Verify: `[command]`

## Hints
[Optional. File paths grouped by area. Canonical patterns (5-10 line excerpts) when the implementer
would otherwise guess wrong. Omit if all paths are obvious from the task descriptions.]
