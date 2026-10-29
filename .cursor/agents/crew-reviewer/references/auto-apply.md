## Self-review auto-apply path (`--auto` mode only)

After outputting the consolidated report, check:

**Gate:** does any finding lack a `Fix:` field, is any finding labeled `[needs more info]`, or would any fix expand or change the approved scope (or user request when no spec exists), change a public contract or schema, touch files outside the reviewed diff, or require a hard-to-reverse or external action?

- **Yes (gate fails):** output the consolidated report normally. Then output:

  > **Auto-apply paused.** N finding(s) need input before applying: [list titles]. Answer them and run `crew review address` to apply the rest.
  > Then output the standard `crew log` + next-step handoff lines for self-review BLOCK.

- **No (gate passes):** do not ask for approval — apply all code fixes inline now:
  1. Collect all findings and their `Fix:` fields.
  2. For each finding: read the affected file(s), apply the fix, write the file.
  3. **Sibling-check:** for every fix that addresses a pattern, scan all other changed branch files for structurally identical instances and apply the same fix.
  4. Run `git add -u` to stage the modified files.
  5. Output a compact summary:
     ```
     Auto-applied: N fixes (N blocking, N attention, N nit) across M file(s)
     Sibling fixes: N additional instances fixed
     ```
  6. Then output `crew log` line and:
     > Next: run `crew commit` to continue, or run `crew review --auto` for another pass.

**Loop extension (`--auto --loop` only):** after the summary above, instead of stopping:

- Re-run `~/.agent/bin/get-diff.sh --stat` to get the updated branch diff.
- Check convergence: does a fresh review of the updated branch diff produce ≤2 findings, all `[nit]` or `[needs more info]`?
  - **Yes (converged):** stop. Output: `Loop complete: converged after N iteration(s).` Then output `crew log` + `crew commit` handoff.
  - **Gate fails on next pass (any `[needs more info]`):** stop. Output: `Loop paused at iteration N: N finding(s) need input.` Then surface the questions.
  - **Hard cap reached (3 iterations):** stop regardless. Output: `Loop stopped: 3 iterations reached without full convergence. N finding(s) remain.` Then output `crew log` + next-step handoff.
  - **Otherwise:** increment iteration counter, run the full review+apply cycle again on the updated branch diff, prepending each cycle's output with `--- Iteration N ---`.

### Changes auto-apply path (`changes --auto` mode only)

After outputting the consolidated report, check:

**Gate:** does any finding lack a `Fix:` field, is any finding labeled `[needs more info]`, or would any fix expand or change the approved scope (or user request when no spec exists), change a public contract or schema, touch files outside the reviewed diff, or require a hard-to-reverse or external action?

- **Yes (gate fails):** output the consolidated report normally. Then output:

  > **Auto-apply paused.** N finding(s) need input before applying: [list titles]. Answer them and run `crew review address` to apply the rest.
  > Then output the standard `crew log` + next-step handoff lines for changes review BLOCK.

- **No (gate passes):** do not ask for approval — apply all code fixes inline now:
  1. Collect all findings and their `Fix:` fields.
  2. For each finding: read the affected file(s), apply the fix, write the file.
  3. **Sibling-check:** for every fix that addresses a pattern (e.g. missing null check, wrong variable name convention), scan all other staged files for structurally identical instances and apply the same fix.
  4. Run `git add -u` to re-stage the modified files.
  5. Output a compact summary:
     ```
     Auto-applied: N fixes (N blocking, N concern, N nit) across M file(s)
     Sibling fixes: N additional instances fixed
     ```
  6. Then output `crew log` line and:
     > Next: run `crew commit` to continue, or run `crew review changes --auto` for another pass.

**Loop extension (`changes --auto --loop` only):** after the summary above, instead of stopping:

- Run `git diff --cached --stat` to get the updated staged diff.
- Check convergence: does a fresh review of the updated staged diff produce ≤2 findings, all `[nit]` or `[needs more info]`?
  - **Yes (converged):** stop. Output: `Loop complete: converged after N iteration(s).` Then output `crew log` + `crew commit` handoff.
  - **Gate fails on next pass (any `[needs more info]`):** stop. Output: `Loop paused at iteration N: N finding(s) need input.` Then surface the questions.
  - **Hard cap reached (3 iterations):** stop regardless. Output: `Loop stopped: 3 iterations reached without full convergence. N finding(s) remain.` Then output `crew log` + next-step handoff.
  - **Otherwise:** increment iteration counter, run the full review+apply cycle again on the updated staged diff, prepending each cycle's output with `--- Iteration N ---`.

### Idea auto-apply path (`idea --auto` mode only)

After outputting the consolidated report, check:

**Gate:** does any finding lack a `Fix:` field, or is any finding labeled `[needs more info]`?

- **Yes (gate fails):** output the consolidated report normally. Then output:

  > **Auto-apply paused.** N finding(s) need input before applying: [list titles]. Answer them and run `crew review address` to apply the rest.
  > Then output the standard `crew log` + next-step handoff lines for idea review BLOCK.

- **No (gate passes):** do not ask for approval — apply all fixes inline now:
  1. Collect all findings and their `Fix:` fields.
  2. Locate the original idea text in context (pasted text or most recent `## Revised Idea` section).
  3. Apply each fix mechanically per its `Fix:` field.
  4. **Sibling-check:** for every fix that addresses a pattern, scan the full idea text for structurally identical instances and apply the same fix to each.
  5. **Self-review pass** (internal, no tool calls): adversarial + product-flow lenses — did the revision introduce any new gap or break any flow? Fix inline if found; note as `(self-review: fixed inline)`.
  6. Append a `## Decisions` section listing any rejected/deferred findings with one-line reasons.
  7. Output the revised idea under `## Revised Idea`.
  8. Output a compact summary:
     ```
     Auto-applied: N fixes (N blocking, N concern, N nit)
     Self-review: clean  ← or: N fixed inline
     ```
  9. Then output the convergence check, `crew log` line, and:
     > Next: run `crew spec` to turn this into a spec, or run `crew review idea --auto` for another pass.

**Loop extension (`idea --auto --loop` only):** after step 9 above, instead of stopping:

- Check the convergence criterion: is the revised idea stable (total findings ≤2, all `[nit]` or `[needs more info]`)?
  - **Yes (converged):** stop. Output: `Loop complete: converged after N iteration(s).` Then output the `crew log` + `crew spec` handoff.
  - **Gate fails on next pass (any `[needs more info]`):** stop. Output: `Loop paused at iteration N: N finding(s) need input.` Then surface the questions.
  - **Hard cap reached (3 iterations):** stop regardless. Output: `Loop stopped: 3 iterations reached without full convergence. N finding(s) remain.` Then output `crew log` + next-step handoff.
  - **Otherwise:** increment iteration counter, run the full review+apply cycle again on the `## Revised Idea` from the previous iteration, prepending each cycle's output with `--- Iteration N ---`.

## Step 9: Extensibility

The reviewer roster is extensible. To add a domain-specific reviewer:

1. Create a new `.cursor/agents/reviewer-<name>.md` file with YAML frontmatter (`name`, `description`, `tools: Read, Grep, Glob, SemanticSearch, mcp__semantic-code-search__map_symbols_by_query, mcp__semantic-code-search__symbol_analysis, mcp__semantic-code-search__discover_directories, mcp__semantic-code-search__read_file_from_chunks`, `readonly: true`, `maxTurns: 12`) and a persona prompt (identity, scope boundaries, focus areas, severity definitions, output format). Reviewer personas are analysis-only — set `readonly: false` only if the persona genuinely needs to write files (e.g. auto-applying fixes), and document why.
2. Add a signal rule in Step 4 of this orchestrator to determine when the reviewer activates
3. Assign a context tier in the dispatch table (Step 6)

For example, an SRE team could add a `reviewer-observability.md` persona that activates on monitoring/alerting files and checks query quality, false positive risk, and alert actionability.
