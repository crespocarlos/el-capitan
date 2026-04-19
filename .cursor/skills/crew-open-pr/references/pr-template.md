# PR Description Template

Use this as the default format unless the repo has its own `.github/PULL_REQUEST_TEMPLATE.md`.

```markdown
closes <GITHUB_ISSUE_URL_OR_NUMBER>

## Summary

One paragraph for engineers. State what changed and why — not how. Write like you're briefing a colleague, not documenting for posterity.

Examples of good summaries:
- "Adds WHERE command to the list of Metrics Experience supported ESQL commands"
- "Synthtrace historical data mode creates as many workers as needed, depending on the time range parameter. When the generated data volume is smaller than the flushBytes threshold of 250k set in the bulk function call, workers would finish quickly, and the process could exit before the ES bulk helper flushed its internal buffer. This PR fixes that"
- "Changes the call to Suggestion API in Discover to set the preferred char type as line if the query contains a timeseries bucket aggregation"

### Identify risks

One sentence on what could go wrong. If it's a safe refactor with no contract changes, say so. If there's a real risk (data loss, breaking API, perf regression), call it out.

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
- If SPEC.md exists, derive the summary from its goal — don't paraphrase the diff.
- **How to test** = **reviewer-only** manual bullets (capped) from SPEC Goal / Acceptance Criteria / diff risk, plus one **automated** line pointing at `crew test` / CI. Do not use runbook.md as the source for reviewer steps.
- If the user confirmed LLM assistance, append `---\n🤖` after all content.
