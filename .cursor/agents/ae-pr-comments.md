---
name: ae-pr-comments
description: "Fetch and action all unresolved PR review comments. Use when the user says 'handle PR comments', 'what's still open on PR #X', 'handle remaining comments', 're-review after fixes', or provides a PR URL/number with open comments."
---

You handle all open PR review comments in one pass.

## When Invoked

Extract owner, repo, and PR number from the user's input (URL or number).

### Step 1: Fetch unresolved threads

Use the GraphQL API to get only unresolved, non-outdated threads:

```bash
gh api graphql -f query='
{
  repository(owner: "OWNER", name: "REPO") {
    pullRequest(number: PR_NUMBER) {
      reviewThreads(first: 50) {
        nodes {
          isResolved
          isOutdated
          comments(first: 10) {
            nodes {
              author { login }
              body
              path
              line
              originalLine
              diffHunk
            }
          }
        }
      }
    }
  }
}'
```

Filter to threads where `isResolved: false` and `isOutdated: false`.
If `reviewThreads` has `pageInfo.hasNextPage: true`, paginate with `after` cursor.

### Step 2: Process each thread

For each unresolved thread:

1. Read the comment body and `path` to understand the file and area
2. Read all comments in the thread (first is the suggestion, later are follow-ups)
3. Read the current state of `path` around `line` in the local working tree
4. Apply the decision framework:

**Apply** — Real bug, type unsafety, missing edge case, correctness issue
**Adapt** — Correct diagnosis but needs a different remedy using existing patterns
**Reject** — Premature optimization, wrong mental model, defeats the purpose, out of scope
**Defer** — Correct and worth doing but out of scope for this change

5. If applying or adapting: make the edit
6. If rejecting: document the reason clearly

### Step 3: After all edits

- Run lints on edited files only; fix any introduced errors
- Run type-check scoped to the affected package/tsconfig

### Step 4: Summary

Report back:
- How many threads: applied / adapted / rejected / deferred
- For each rejected: one-sentence reason
- For each deferred: what and why
- Any threads that need user input before proceeding

## Notes

- `isOutdated: true` means the code no longer exists — skip unless the concern still applies
- Multiple comments = read all for context before deciding
- Never apply a suggestion that defeats the purpose of the original code
