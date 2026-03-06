---
name: ae-pr-review
description: "Deep-review a Pull Request. Use when the user says 'review PR #X', 'review this PR', 'look at this PR', or provides a PR URL to review."
---

You review Pull Requests by reading beyond the diff to understand intent, trace impact, and find what's missing.

## References

Read these before starting — they contain the commands and patterns you'll need:

- [commands.md](./references/commands.md) — gh commands for fetching PRs, finding consumers, verifying tests. Includes strategies for large diffs.
- [review-patterns.md](./references/review-patterns.md) — size-based review strategy and what to look for by change type (feature, bug fix, refactor, type change, tests).

## When Invoked

Extract owner, repo, and PR number from the user's input (URL, number, or current checkout).

### Step 1: Understand intent

Fetch PR metadata and any linked issues (see [commands.md](./references/commands.md)). Summarize the stated intent in one sentence. This is your reference — the entire review evaluates whether the code achieves this intent correctly.

### Step 2: Read the diff

Fetch the diff. For large PRs (>500 lines), triage by file first — don't read the entire diff at once. See [commands.md](./references/commands.md) for size-based strategies.

Identify:
- Which files changed and why (new feature, bug fix, refactor, test)
- Which changes are structural (new files, moved code) vs behavioral (logic changes)
- The **spine** — the 2-3 key decisions everything else flows from

### Step 3: Read full files

For every file with behavioral changes, read the **full file** — not just the diff hunks. The diff shows what changed; the full file shows what the change lives inside.

Focus on:
- What surrounds the changed code (error handling, state, lifecycle)
- What the changed function/component is responsible for
- What contracts (types, interfaces, API shapes) the change affects

### Step 4: Trace impact

For changed exports, public functions, or type definitions — find their consumers (see [commands.md](./references/commands.md)).

This catches the most important class of bugs: changes that are locally correct but break something downstream.

### Step 5: Verify test coverage

For each behavioral change:

1. Is there a test that exercises the changed path?
2. Does the test assertion actually verify the **new** behavior — not just that the code runs?
3. Are edge cases covered? (empty input, error paths, boundary values)
4. If tests were modified, do the old assertions still hold or were they weakened?

If there are no test changes for a behavioral change, flag it.

### Step 6: Check project conventions

Read the repo's `AGENTS.md`, `CLAUDE.md`, or contributing guide. Only flag deviations that cause real problems — not stylistic preferences the linter handles.

### Step 7: Produce the review

Consult [review-patterns.md](./references/review-patterns.md) for what to look for based on the change type and PR size.

Structure findings by severity:

**Critical** — blocks merge. Correctness bugs, data loss risk, security issues, broken consumers.

**Important** — should fix before merge. Missing error handling, inadequate test coverage, API contract issues, performance concerns for hot paths.

**Consider** — worth discussing. Alternative approaches, simplification opportunities, patterns that diverge from codebase conventions.

For each finding:
- Name the file and line area
- State what you found and why it matters
- If suggesting a change, show the concrete fix or describe the approach

### Step 8: Overall assessment

End with:
- **Intent match**: does the code achieve what the PR description claims? (yes / partially / no)
- **Completeness**: is anything missing? (tests, docs, migration, changelog)
- **Design**: is the approach the simplest that could work? Would you do it differently?
- **Verdict**: approve / request changes / needs discussion — one sentence why

## Rules

- Read full files, not just diffs. Context is where the bugs hide.
- Find what's MISSING, not just what's wrong. Missing tests, missing error handling, missing consumer updates, missing docs.
- Be specific. "Consider error handling" is useless. "The `fetchData` call on line 42 has no catch — if the API returns 429, this crashes the polling loop" is useful.
- Don't comment on style, formatting, or naming unless it causes actual confusion. The linter handles style.
- For large PRs, identify the spine first and review that thoroughly. Don't try to review every line — focus on the decisions that matter.
- Acknowledge what's done well. If the approach is clean, say so.
- Never pad reviews with filler. Zero findings is a valid outcome — "this is clean, approve" is a complete review.
