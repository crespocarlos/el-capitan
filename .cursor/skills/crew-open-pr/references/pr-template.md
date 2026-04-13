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

Steps to verify the change for a reviewer. Derive from the spec's `## Tests` section:
- `type: visual` and `type: judgment` items from `### Manual` → list these directly as reviewer steps
- `type: http`, `type: data`, `type: script` items → summarise as "run `crew test` to execute automated checks"
- If `$TASK_DIR/runbook.md` exists → reference it: "See runbook at `<path>` for full validation procedure"

If no `## Tests` section exists in the spec, keep this section brief or omit it. Never invent steps.
```

## Rules

- `closes <URL_OR_NUMBER>` goes at the top, before the summary. Use the full GitHub issue URL (e.g. `closes https://github.com/org/repo/issues/123`) or `closes #123` if same repo. GitHub auto-closes from the body.
- Summary tone: direct, for engineers. No fluff, no "This PR aims to..."
- If SPEC.md exists, derive the summary from its goal — don't paraphrase the diff.
- "How to test" derives from `## Tests > ### Manual` — `type: visual` and `type: judgment` items are the reviewer steps. Reference `runbook.md` if present. Automated items (`type: http/data/script`) summarise as "run `crew test`". Never invent steps.
- If the user confirmed LLM assistance, append `---\n🤖` after all content.
