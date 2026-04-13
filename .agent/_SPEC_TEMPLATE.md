# Spec: [title]

## Type: [feature | bugfix | refactor | chore | docs]
## Status: DRAFTING
## Phase: spec → implement → test → diff-check → commit → pr-open → done
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

## Design Constraints
Structural rules the implementation must follow. Each constraint is verifiable by code inspection. The implementer checks these BEFORE marking tasks complete.

- [ ] [Constraint about function responsibility boundaries — which functions/files should NOT grow]
- [ ] [Constraint about API surface / return types — minimize fields, one array per consumer]
- [ ] [Constraint about consistency with existing patterns — return values vs mutation, pure vs stateful]
- [ ] [Constraint about deduplication — if two outputs share derived data, name the single function]

## Tasks
Atomic units of work, organized by architectural boundary (one new function/module per task, not by modification type). Each task is independently verifiable.

- [ ] 1) [Task name]
  - **Change**: [What to do]
  - **Files**: [Files to create or modify]
  - **Acceptance**: [How to verify this task alone]

- [ ] 2) [Task name]
  - **Change**: [What to do]
  - **Files**: [Files to create or modify]
  - **Acceptance**: [How to verify this task alone]

## Tests
<!-- Specwriter: include only blocks for discovered frameworks. Omit unused layers.
     Add runbook.md when change involves agent behavior, workflow orchestration,
     data pipeline outputs, or cross-service integration. -->

### Unit
- **Framework**: [jest | vitest | none]
- **Command**: `<test command or "none">`
- **Scenarios**:
  - [ ] [Scenario 1]

### Integration
- **Framework**: [FTR | none]
- **Command**: `<test command or "none">`
- **Scenarios**:
  - [ ] [Scenario 1]

### E2E
- **Framework**: [playwright | none]
- **Command**: `<test command or "none">`
- **Scenarios**:
  - [ ] [Scenario 1]

### Manual
- [ ] type: http — `curl /api/endpoint` returns 200 **Pass:** HTTP 200
- [ ] type: data — `curl .../index/_count` **Pass:** count > 0
- [ ] type: script — `npx tsx scripts/check.ts` **Pass:** exit 0
- [ ] type: visual — [what to look at in the UI]
- [ ] type: judgment — [qualitative/semantic assessment]

## References
[For each non-trivial implementation decision in this spec, the existing file that already made that decision. Show the specific pattern (10-15 lines max). Only include what the implementer would otherwise get wrong by guessing — if a decision has only one reasonable answer, skip it.]
