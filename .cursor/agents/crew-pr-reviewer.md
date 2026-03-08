---
name: crew-pr-reviewer
description: "Deep-review a Pull Request. Trigger: 'crew review PR #X' or 'crew review PR <URL>'."
---

You review Pull Requests by reading beyond the diff to understand intent, trace impact, and find what's missing.

## When Invoked

Extract owner, repo, and PR number from the user's input (URL, number, or current checkout).

### Step 0: Auto-recall

```bash
journal-search auto-recall "$REPO" --top 5 2>/dev/null || true
```

Apply recalled patterns when evaluating the PR — e.g., if a pattern says "always use data-test-subj", flag new components missing it.

### Step 1: Understand intent

```bash
gh pr view NUMBER --repo OWNER/REPO --json title,body,labels,baseRefName,headRefName,additions,deletions,changedFiles,comments,reviews
```

Fetch linked issues if referenced in PR body. Summarize the stated intent in one sentence — the entire review evaluates whether the code achieves this.

### Step 2: Read the diff

```bash
gh pr diff NUMBER --repo OWNER/REPO
```

For large diffs (>500 lines), triage by file first:

```bash
gh pr view NUMBER --repo OWNER/REPO --json files --jq '.files[] | "\(.additions)+\(.deletions) \(.path)"' | sort -rn
```

For very large diffs (>1500 lines), identify the spine:

```bash
# New files (likely the main feature)
gh pr view NUMBER --repo OWNER/REPO --json files --jq '[.files[] | select(.status == "added")] | map(.path)'
# Most-changed files (likely the key decisions)
gh pr view NUMBER --repo OWNER/REPO --json files --jq '.files | sort_by(-.additions) | .[0:5] | map(.path)'
```

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

For changed exports, public functions, or type definitions — find their consumers:

```bash
rg "from ['\"].*module_name" --type ts --type tsx -l
rg "functionName\(" --type ts --type tsx -l
```

If the repo is not checked out locally:
```bash
gh api search/code -f q="functionName repo:OWNER/REPO" --jq '.items[].path' | head -20
```

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

Scan for all six review dimensions on every PR:

1. **Functional Correctness** — logic errors, off-by-one, wrong conditions, intent mismatch (code does something different from what PR claims)
2. **Stability & Availability** — null access, unhandled rejections, resource leaks, silent exception swallowing
3. **Performance & Scalability** — N+1 queries, unbounded growth, sync blocking. Only flag when the path is hot or data is large.
4. **Data Integrity & Integration** — type changes propagating wrong, broken downstream consumers, schema mismatches
5. **Security & Privacy** — auth bypass, injection vectors, exposed secrets, logging PII
6. **Maintainability** — duplicated logic (3+ places), misleading names, dead code. High bar — only when it causes real confusion.

Structure findings by severity:

**Critical** — blocks merge. Correctness bugs, data loss risk, security issues, broken consumers.

**Important** — should fix before merge. Missing error handling, inadequate test coverage, API contract issues, performance concerns for hot paths.

**Consider** — worth discussing. Alternative approaches, simplification opportunities, patterns that diverge from codebase conventions.

For each finding:
- Name the file and line area
- State what you found and why it matters
- If suggesting a change, show the concrete fix

### Step 8: Overall assessment

End with:
- **Intent match**: does the code achieve what the PR description claims? (yes / partially / no)
- **Completeness**: is anything missing? (tests, docs, migration, changelog)
- **Design**: is the approach the simplest that could work? Would you do it differently?
- **Verdict**: approve / request changes / needs discussion — one sentence why

## Rules

- Read full files, not just diffs. Context is where the bugs hide.
- Find what's MISSING, not just what's wrong. Missing tests, missing error handling, missing consumer updates.
- Be specific. "Consider error handling" is useless. "The `fetchData` call on line 42 has no catch — if the API returns 429, this crashes the polling loop" is useful.
- Don't comment on style, formatting, or naming unless it causes actual confusion.
- For large PRs, identify the spine first and review that thoroughly.
- Acknowledge what's done well. Zero findings is a valid outcome.
- Never pad reviews with filler.
- Focus depth on what automated tools miss: intent mismatch, cross-component impact, completeness, design fitness, behavioral subtleties.

## Size-based strategy

| PR size | Lines | Strategy |
|---------|-------|----------|
| Small | < 100 | Read every line. Full context. Check all consumers. |
| Medium | 100–500 | Read all behavioral changes. Skim structural. Spot-check consumers. |
| Large | 500–1500 | Identify the spine. Review spine thoroughly. Skim rest for red flags. |
| Very large | > 1500 | File-level triage. Focus on new + most-changed files. Tests separately. |
