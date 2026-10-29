# PR Description Template

Use this as the default format unless the repo has its own `.github/PULL_REQUEST_TEMPLATE.md`.

```markdown
closes <GITHUB_ISSUE_URL_OR_NUMBER>

## Summary

Write this like a human engineer updating another engineer. Lead with user-visible impact and intent; add implementation detail only when it helps a reviewer judge scope or risk. Prioritize intent and impact over file-by-file mechanics.

Gate the length to the change:
- **Small** (≤3 files, no new API/exports, local fix): one or two sentences.
- **Medium** (a feature or behavior change): one paragraph on impact, plus one sentence on the key internal change if it aids review.
- **Large** (cross-cutting, new abstraction, contract/migration): a short paragraph on impact, then a second on the notable architectural decision and why.

When in doubt, write less.

Examples of good summaries (note the shape, not the content):
- Lead with what the user can now do and where, then add one sentence of why it matters.
- Follow with an optional paragraph naming the key server/internal change and the reason it exists (shared abstraction, contract alignment, perf fix).
- Explain a bug fix as the observable symptom and its root cause, not the lines touched.

Examples of bad summaries (avoid this shape):
- A list of renamed symbols/files/constants with counts.
- Section headers grouping changes by layer ("Workflow changes", "TypeScript cascade") followed by per-file bullets.
- Vague restatements of the diff ("refactors implementation details to align terminology").

### How to test

**Goal:** Only steps a **human reviewer** can perform on this PR without the full operator harness (at most **3–5** bullets). Never paste long integration matrices or internal runbooks.

Derive from, in order:
1. SPEC **Goal** and **high-signal** bullets under **Acceptance Criteria** (Requirements / Non-regression) — distill to reviewer-sized checks.
2. **Diff risk** — what changed files or behaviors a reviewer should spot-check (UI path, config knob, API response shape).

**Automated:** Typed commands under SPEC `## Tests` (`### Unit` / `### Integration` / `### E2E` / `### Validation`) are run via **`crew test`** (and CI when applicable). One line in the PR body is enough, e.g. "Automated: `crew test` passes in the worktree."

**Do not:** Pull reviewer steps from `$TASK_DIR/runbook.md` (local artifact, scriptable-only policy). Do not invent steps.

If no SPEC.md exists, keep this section brief or omit it. Never invent steps.
```

## Rules

- `closes <URL_OR_NUMBER>` goes at the top, before the summary. Use the full GitHub issue URL (e.g. `closes https://github.com/org/repo/issues/123`) or `closes #123` if same repo. GitHub auto-closes from the body.
- Summary tone: direct, for engineers. No fluff, no "This PR aims to..."
- If SPEC.md exists, derive the summary from its goal and user impact — don't paraphrase the diff as a change log.
- Avoid layer-grouped section headers or long bullet inventories of renamed fields/files in the Summary.
- **How to test** = **reviewer-only** manual bullets (capped) from SPEC Goal / Acceptance Criteria / diff risk, plus one **automated** line pointing at `crew test` / CI. Do not use runbook.md as the source for reviewer steps.
