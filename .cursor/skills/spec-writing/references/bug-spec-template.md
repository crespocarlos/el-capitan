# Spec: [title]

## Type: bugfix
## Branch: [bugfix/short-description]
## Status
DRAFTING

## Summary
[What's broken and the minimal fix boundary. Link to issue.]

Reproduction: [steps or failing command] Current behavior: [what happens] Expected behavior: [what
should happen] Unchanged behavior: [adjacent behavior the fix must not alter] Out of scope:
[adjacent work — one-phrase reason each]

## Open questions
- [NEEDS CLARIFICATION: question — what breaks if guessed wrong] [Delete this section when empty.]

## Acceptance criteria
- [ ] WHEN [reproduction] THEN [expected behavior] — verify: `[regression test command]`
- [ ] Non-regression: [unchanged behavior preserved] — verify: `[command]`

## Tests
[Keep only the layers that apply. Each kept layer needs a runnable command.]
### Unit
- **Command**: `[command]`
### Validation
- **Command**: `[lint, type-check, or other quality gate]`

## Tasks
- [ ] 1) Add a failing regression test
  - [Test file and the reproduction it encodes.]
  - Verify: `[command]` fails before the fix
- [ ] 2) [Fix]
  - [What to change, which files. Stay within the reproduction path.]
  - Verify: `[command]` passes

## Hints
[Optional. File paths, stack traces, canonical patterns.]
