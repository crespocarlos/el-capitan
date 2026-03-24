# Issue Templates

Use these templates to structure GitHub issues. If the target repo has `.github/ISSUE_TEMPLATE/` with its own templates, prefer those — read them and fill in their sections instead of using the defaults below.

## Bug Report

```markdown
## Summary

One-paragraph description of the bug. State what's broken, where it happens, and the impact.

## How to reproduce

1. Step-by-step instructions to trigger the bug
2. Include specific inputs, URLs, or configurations
3. Note the environment (browser, OS, version) if relevant

## Evidence

Paste relevant error logs, screenshots, API responses, or profiling data here.

## Expected behavior

What should happen instead.

## Acceptance Criteria

- [ ] The bug no longer reproduces following the steps above
- [ ] (add criteria specific to the fix)
```

## Feature Request

```markdown
## Summary

One-paragraph description of the feature. State what it does and who benefits.

## Motivation

Why this feature is needed. Link to user feedback, metrics, or upstream issues if available.

## Acceptance Criteria

- [ ] (specific, testable criteria for the feature)
- [ ] (add as many as needed)
```

## Template Selection

- **Bug**: The user describes something broken, an error, unexpected behavior, a regression, or a crash. Default to bug if the classification is ambiguous.
- **Feature**: The user describes something new — a capability, workflow, integration, or enhancement to existing behavior.
- Append `---\n🤖` after all content.
