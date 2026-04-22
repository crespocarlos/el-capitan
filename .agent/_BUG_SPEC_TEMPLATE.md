# Spec: [title]

## Type: [feature | bugfix | refactor | chore | docs]
## Status
DRAFTING
## Phase: spec → implement → test → review → commit → pr-open → done
## Current: spec
## Next: implement

## Context
- **Reproduction steps:** [numbered list]
- **Minimal fix boundary:** [narrowest change that stops the reproduction]
- **Problem**: [What exists today and what's wrong with it. Link to issue/PR.]
- **Scope**:
  - In-scope: [What this change covers]
  - Out-of-scope: [What this change does NOT cover — prevents scope creep]
- **Repo touchpoints**: [Files and modules that will be modified]

## Goal
Fix the reproduction without changing behavior outside it.

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

- [ ] No changes outside the reproduction path.
- [ ] [Constraint about function responsibility boundaries — which functions/files should NOT grow]
- [ ] [Constraint about API surface / return types — minimize fields, one array per consumer]
- [ ] [Constraint about consistency with existing patterns — return values vs mutation, pure vs stateful]
- [ ] [Constraint about deduplication — if two outputs share derived data, name the single function]
- [ ] **Run discipline (optional):** After **three** failed verify attempts on the same task **Acceptance** command, **stop and report** in REPORT.md. Do **not** run the **full** repository test suite under one task unless **Acceptance** explicitly names that command. Prose-only **MAX_TOOL_ROUNDS** in Acceptance is allowed (not auto-enforced in v1).

## Tasks
<!-- Fix tasks are scoped to the reproduction path. If a task touches a file not in the repro, split it or justify it. -->
Atomic units of work, organized by architectural boundary (one new function/module per task, not by modification type). Each task is independently verifiable.

- [ ] 1) [Task name]
  - **Change**: [What to do]
  - **Files**: [Files to create or modify]
  - **Acceptance**: **Dry-run:** `[safe repro or dry-run]` passes. **Live:** `[narrow fix command]` passes after approval.

- [ ] 2) [Task name]
  - **Change**: [What to do]
  - **Files**: [Files to create or modify]
  - **Acceptance**: [How to verify this task alone]

## Tests
<!-- Specwriter: include only blocks for discovered frameworks. Omit unused layers.
     ## Tests = invocable commands only. Harness / human checks → Acceptance Criteria
     and task Acceptance. Optional runbook.md = scriptable only. -->

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

### Validation
<!-- One-shot validators / schema gates (agent-builder workflow validate, linters, codegen).
     Distinct from behavioral E2E. Use "none" when not applicable. -->
- **Framework**: [agent-builder | shell | none]
- **Command**: `<one-shot CLI or "none">`
- **Scenarios**:
  - [ ] [Scenario 1]

## Additional Context
<!-- Optional. Append-only session notes during implementation. -->

## References
[File paths to canonical examples the implementer should read. Include key patterns inline when the spec must be self-contained.]
