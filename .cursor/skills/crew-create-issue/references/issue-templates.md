# Issue Templates

Use these templates to structure GitHub issues. If the target repo has `.github/ISSUE_TEMPLATE/` with its own templates, prefer those — read them and fill in their sections instead.

## Default (feature / task)

```markdown
## 📓 Summary

One-paragraph description of what this is and why it matters.

## ✔️ Acceptance criteria

- [ ] (specific, testable — observable outcome, not implementation step)
- [ ] (add as many as needed)

## 💡 Implementation hints

- (optional — key files, ordered steps, known risks, merge order constraints)
```

## Bug Report

```markdown
## 📓 Summary

One-paragraph description of the bug. State what's broken, where it happens, and the impact.

## How to reproduce

1. Step-by-step instructions to trigger the bug
2. Include specific inputs, URLs, or configurations
3. Note the environment (browser, OS, version) if relevant

## Evidence

Paste relevant error logs, screenshots, API responses, or profiling data here.

## Expected behavior

What should happen instead.

## ✔️ Acceptance criteria

- [ ] The bug no longer reproduces following the steps above
- [ ] (add criteria specific to the fix)
```

## Template Selection

- **Default**: use for features, tasks, refactors, and enhancements. This is the primary template.
- **Bug**: use when the user describes something broken, an error, unexpected behavior, a regression, or a crash.

## Writing notes

- Acceptance criteria: each item should be **observable and testable** — describe the outcome, not the implementation step. Good: "GET /api/foo returns 200 with field `x`". Bad: "Update the handler to include field `x`".
- Implementation hints: only include if the session has context about approach, risky areas, merge order, or key files. Leave the section out if there's nothing substantive to say.
- Append `---\n🤖` after all content.
