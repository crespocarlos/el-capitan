# Issue Templates

**Read this file before drafting.** If the target repo has `.github/ISSUE_TEMPLATE/` with its own templates, prefer those — read them and fill in their sections instead. When that directory is missing (404), use the fallback templates below.

## Default (feature / task)

```markdown
## 📓 Summary

One-paragraph description of what this is and why it matters.

## ✔️ Acceptance criteria

- [ ] (specific, testable — observable outcome, not implementation step)
- [ ] (add as many as needed)

## 💡 Implementation hints

- (optional — key files, ordered steps, known risks, merge order constraints)

---
🤖
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

---
🤖
```

## Template Selection

- **Default**: use for features, tasks, refactors, and enhancements. This is the primary template.
- **Bug**: use when the user describes something broken, an error, unexpected behavior, a regression, or a crash.

## Title conventions

Discover how issues are titled in the target repo — do not assume a prefix pattern:

```bash
GH_PAGER=cat gh issue list --repo OWNER/REPO --limit 10 --json title
```

Common patterns (use only when the repo already uses them):

- `[Workstream] Short imperative description`
- `[Workstream][Area] Short imperative description`
- Plain imperative description with no prefix

Match the dominant style in recent issues. Omit a workstream prefix only when the work is genuinely cross-cutting.

## Label conventions

List labels and pick the best fit — do not assume label names:

```bash
GH_PAGER=cat gh label list --repo OWNER/REPO --limit 30
```

Typical mappings (apply only when the label exists in that repo):

| Intent | Look for labels like |
|---|---|
| Broken behavior / regression | `bug` |
| New capability | `enhancement`, `feature` |
| Unresolved design decision in AC | `needs design`, `needs refinement` |
| Workstream / team ownership | repo-specific labels from `gh label list` |

## Writing notes

- **Restructure, don't dump.** Long session analysis (tables, numbered findings, Option A/B) belongs *inside* Summary, Acceptance criteria, and Implementation hints — not as separate top-level sections.
- **Acceptance criteria:** each item should be **observable and testable** — describe the outcome, not the implementation step. Good: "`GET /api/foo` returns 200 with field `x`". Bad: "Update the handler to include field `x`".
- **Implementation hints:** group by area (`**Routes**`, `**Schema**`, `**UI**`). Include concrete file paths when the session has them. Omit the section only if there is nothing substantive to say.
- **Footer:** append `---` then `🤖` on the next line after all content.

## Anti-patterns (do not produce these)

```markdown
## Summary          ← wrong: missing 📓 emoji
## Issues           ← wrong: not a template section
## Domain hierarchy ← wrong: fold into Summary or Implementation hints
## Proposed fix     ← wrong: fold decisions into AC as "Decision required: …"
```

## Filled example (generic refactor)

```markdown
## 📓 Summary

The module uses inconsistent naming for the same concept across directories, routes, types, and hooks. Contributors cannot predict which identifier to use, and several public names describe the wrong domain object.

## ✔️ Acceptance criteria

- [ ] One documented rule for code-facing identifiers, applied consistently across directories, routes, types, and hooks
- [ ] Misleading response types and fields renamed to reflect what they actually return
- [ ] Hook and function names align with the data each one fetches
- [ ] Internal routes follow one namespace prefix for domain entities
- [ ] **Decision required:** team picks the canonical naming scheme before implementation starts

## 💡 Implementation hints

- **Routes**: list affected route dirs from the session
- **Hooks / clients**: list affected hook and client files
- **Schema / types**: list packages and barrel exports to update
- **Tests**: note registry, API, and snapshot tests that assert old names

---
🤖
```
