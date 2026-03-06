---
name: ae-pr-resolver
description: "Fetch and action all unresolved PR review comments. Use when the user says 'handle PR comments', 'what's still open on PR #X', 'handle remaining comments', 're-review after fixes', or provides a PR URL/number with open comments."
---

You handle all open PR review comments in one pass: fetch, triage, evaluate, act, resolve, report.

## When Invoked

Extract owner, repo, and PR number from the user's input (URL or number).

### Step 1: FETCH — Get all review threads with pagination

Use GraphQL with cursor-based pagination. REST endpoints and MCP `get_review_comments` cap at 100 results without clearly surfacing `hasNextPage` — always use GraphQL for thread discovery.

Request both `id` (GraphQL node ID, for `resolveReviewThread` mutation) and `databaseId` (for REST reply endpoint) in the same query:

```bash
gh api graphql -f query='
{
  repository(owner: "OWNER", name: "REPO") {
    pullRequest(number: PR_NUMBER) {
      reviewThreads(first: 100) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 10) {
            nodes {
              id
              databaseId
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

If `pageInfo.hasNextPage` is true, paginate with `after: "CURSOR"` until all threads are fetched.

Filter to threads where `isResolved: false` and `isOutdated: false`.

### Step 2: TRIAGE — Classify unresolved threads

Before reading code:
- Skip bot-only threads with no human follow-up (CodeRabbit, copilot-bot, etc.) unless the concern looks legitimate at a glance
- Group remaining threads by file path for efficient batch reading

### Step 3: EVALUATE — Run ae-pr-comments-eval per thread

For each unresolved thread, evaluate it using the **ae-pr-comments-eval** skill (read `~/.cursor/skills/ae-pr-comments-eval/SKILL.md`):

1. Read the comment body and `path` to understand the file and area
2. Read all comments in the thread (first is the suggestion, later are follow-ups)
3. Read the current state of `path` around `line` in the local working tree
4. Read related test files — tests that explicitly validate the flagged behavior are strong evidence it's intentional
5. Apply the ae-pr-comments-eval decision framework to classify as **Apply**, **Adapt**, **Reject**, or **Defer**

### Step 4: ACT — Execute decisions

- **Apply/Adapt**: make the edit, run lints on edited files, run type-check scoped to the affected package
- **Reject**: prepare a clear rationale explaining the specific reason
- **Defer**: note what it is and why it's out of scope for this change

### Step 5: RESOLVE — Close threads on GitHub

For each thread, two operations are needed (both IDs come from the Step 1 query):

1. **Reply** with the verdict and rationale. Always prefix with 🤖 so agent comments are distinguishable from human ones (format defined in ae-pr-comments-eval). Use the `databaseId` from the first comment in the thread:
   ```bash
   gh api repos/OWNER/REPO/pulls/PR_NUMBER/comments/DATABASE_ID/replies -f body="🤖 **Verdict** — rationale"
   ```

2. **Resolve** the thread using the GraphQL node `id` from the thread:
   ```bash
   gh api graphql -f query='
   mutation {
     resolveReviewThread(input: {threadId: "THREAD_NODE_ID"}) {
       thread { isResolved }
     }
   }'
   ```

### Step 6: REPORT — Summary

Report back with a table:

| Thread | File | Reviewer | Verdict | Rationale |
|--------|------|----------|---------|-----------|
| #1 | path/to/file.ts:42 | @reviewer | Reject | Wrong mental model — test validates this behavior |
| ... | ... | ... | ... | ... |

Summary counts: N applied / N adapted / N rejected / N deferred

For each thread that needs user input before proceeding, surface it explicitly.

## Notes

- `isOutdated: true` means the code has changed since the comment — skip unless the concern still applies to the current code
- Multiple comments in a thread = read all for context before deciding (first is the suggestion, later are follow-ups and discussion)
- Never apply a suggestion that defeats the purpose of the original code
- GraphQL is the only reliable way to get thread resolution state + both ID types in a single round-trip
