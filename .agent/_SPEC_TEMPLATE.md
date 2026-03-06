# Spec: [title]

## Status: DRAFTING
## Phase: spec → implement → diff-review → commit → push → pr-comments → done
## Current: spec
## Next: implement

## Context
- **Problem**: [What exists today and what's wrong with it. Link to issue/PR.]
- **Scope**:
  - In-scope: [What this change covers]
  - Out-of-scope: [What this change does NOT cover — prevents scope creep]
- **Repo touchpoints**: [Files and modules that will be modified]

## Goal
[One sentence.]

## Acceptance Criteria

### Requirements (inferred from the ticket)
What the change must achieve. Each criterion states a positive, observable outcome.

- [ ] [Criterion that directly addresses what the ticket prescribes]
- [ ] [Criterion that directly addresses what the ticket prescribes]

### Non-regression
Nothing existing breaks. These may be verified by code inspection rather than a command.

- [ ] [Existing behavior X still works as before]
- [ ] [Downstream consumers of modified APIs/types are unaffected]

### Quality gates
Baseline hygiene. Follow the repo's AGENTS.md (or equivalent contributing guide) for required validation commands. Scope commands to the affected package — never run repo-wide checks.

- [ ] [Validation commands from AGENTS.md, scoped to affected package]

## Tasks
Atomic units of work. Each task is independently verifiable.

- [ ] 1) [Task name]
  - **Change**: [What to do]
  - **Files**: [Files to create or modify]
  - **Acceptance**: [How to verify this task alone]

- [ ] 2) [Task name]
  - **Change**: [What to do]
  - **Files**: [Files to create or modify]
  - **Acceptance**: [How to verify this task alone]

## References
[File paths to canonical examples the implementer should read. Include key patterns inline when the spec must be self-contained.]
