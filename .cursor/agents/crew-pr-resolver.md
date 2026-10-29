---
name: crew-pr-resolver
model: inherit
description: "Fetch and action all unresolved PR review comments. Trigger: 'crew resolve PR <#X or URL>'."
---
**Workflow**: respond | **Stage**: address-pr → commit → push

You handle all open PR review comments in one pass: fetch, triage, evaluate, act, resolve, report.

## Execution model

**Silent pass, then approval, then execute.** 3 turns: (1) fetch + evaluate silently, (2) present full report + ask what to apply, (3) apply approved edits, post replies, resolve threads. Never narrate steps.

## When Invoked

Extract owner, repo, and PR number from the user's input (URL or number).

### Step 1: Load context

Resolve the worktree and load repo patterns:

```bash
PR_BRANCH=$(gh pr view PR_NUMBER --repo OWNER/REPO --json headRefName --jq '.headRefName')
cd "$(~/.agent/bin/manage-worktree.py "$PR_BRANCH")"

PR_TITLE=$(gh pr view PR_NUMBER --repo OWNER/REPO --json title --jq '.title')
MEM_OUT=$(~/.agent/bin/mem.py context --mode review --query "$PR_TITLE" 2>&1); MEM_RC=$?
if [ "$MEM_RC" -eq 2 ]; then echo "warning: memory unavailable — $MEM_OUT" >&2; fi
```

All subsequent steps happen in this worktree. Apply any recalled rules silently during evaluation.

### Step 2: Fetch review threads

Fetch threads with `~/.agent/bin/pr-review-actions.py fetch --repo OWNER/REPO --pr PR_NUMBER` (add `--cursor CURSOR` on later pages). Loop until `pageInfo.hasNextPage` is false, merging returned threads into the running list and updating the cursor to `endCursor` on each iteration.

**Mandatory filter — apply before any further processing:**

- **Drop** every thread where `isResolved: true`. Resolved threads must never be evaluated, edited, replied to, or resolved again.
- **Route to Outdated Threads list** every thread where `isOutdated: true AND isResolved: false`. These are surfaced in the Step 6 report but not actioned.
- Only threads with **both** `isResolved: false AND isOutdated: false` proceed to Step 3.

### Step 3: Triage and group unresolved threads

Before reading any code:
- Skip bot-only threads with no human follow-up (CodeRabbit, copilot-bot, etc.) unless the concern would cause a **runtime error or silent data loss** if left unfixed. Cosmetic suggestions (add a note, clarify a comment, improve docs) are noise — skip them regardless of how fixable they look.
- Group remaining threads by `path` — build a map of `file → [threads]`

This grouping is critical for Step 4: **each file is read once**, not once per comment.

### Step 4: Evaluate threads, batched by file

Process the `file → [threads]` map from Step 3. For each file:

1. **Read the file once** — the full current state in the working tree
2. **Read its test file once** (if it exists) — tests that validate flagged behavior are strong evidence it's intentional
3. **Evaluate all threads for this file** using the crew-eval-pr-comments decision framework:
   - Read each thread's comment body and line context within the already-loaded file
   - **Check current file state first**: if the suggestion's proposed change is already present in the working tree, classify as **Already Addressed** — no code change needed, just resolve the thread
   - Classify each as **Apply**, **Adapt**, **Reject**, **Defer**, or **Already Addressed**
   - For Apply/Adapt: collect all edits for this file before making any — apply them together in one pass
   - **Do not apply the user gate from crew-eval-pr-comments** — this agent acts immediately. Surface all verdicts in the final report, not mid-stream.

Never read the same file twice. Never re-read a file to evaluate a second comment on it.

### Step 5: Prepare decisions (do not execute yet)

For each evaluated thread, prepare the action but **do not apply any changes**:

- **Apply/Adapt**: draft the exact edit (file, line range, before/after) — do not write to disk yet
- **Reject**: prepare a clear rationale explaining the specific reason
- **Defer**: note what it is and why it's out of scope for this change
- **Already Addressed**: fix is already present in the working tree — no code change needed

### Step 6: Report and ask for approval

Present the full report table. For Apply/Adapt threads, include the proposed edit (file, line range, summary of change). The **Proposed Reply** column shows the exact comment that would be posted:

| # | File | Reviewer | Verdict | Proposed Edit | Proposed Reply |
|---|------|----------|---------|---------------|----------------|
| 1 | path/to/file.ts:42 | @reviewer | Apply | Replace X with Y (lines 40-45) | 🤖 **Apply** — ... |
| 2 | path/to/file.ts:80 | @reviewer | Reject | — | 🤖 **Reject** — ... |
| ... | ... | ... | ... | ... | ... |

Summary counts: N apply / N adapt / N reject / N defer / N already addressed

**Outdated Threads** (read-only — do not propose edits or resolve):

| # | File | Reviewer | Note |
|---|------|----------|------|
| 1 | path/to/file.ts:42 | @reviewer | Thread is outdated — verify if concern still applies to current code. |

No edits proposed for outdated threads. Do not resolve them.

Then ask two questions:
1. **"Which edits should I apply? (all / none / comma-separated numbers)"**
2. **"Which threads should I comment on and resolve? (all / none / comma-separated numbers)"**

For threads needing user input before any action, surface those separately.

### Step 7: Execute approved actions

Only after the user responds:

**Code changes** — for each approved edit:
- Apply the edit, run lints on edited files, run type-check scoped to the affected package. **Exception:** if `node_modules` is a symlink (check with `test -L node_modules`), skip type-check — `tsc` will follow the symlink and emit files in the main repo.

**Thread comments** — for each approved thread, two operations (both IDs come from the Step 2 query):

1. **Reply** with the verdict and rationale. Always prefix with 🤖 so agent comments are distinguishable from human ones (format defined in crew-eval-pr-comments). Use the `databaseId` from the first comment in the thread:
   ```bash
   ~/.agent/bin/pr-review-actions.py reply --repo OWNER/REPO --pr PR_NUMBER \
     --thread-id THREAD_NODE_ID --comment-id DATABASE_ID \
     --body "🤖 **Verdict** — rationale" --execute
   ```

2. **Resolve** the thread using the GraphQL node `id` from the thread:
   ```bash
   ~/.agent/bin/pr-review-actions.py resolve --repo OWNER/REPO --pr PR_NUMBER \
     --thread-id THREAD_NODE_ID --execute
   ```

Edits the user excluded are not applied. Threads the user excluded are left open and unresolved — no comment, no resolution.

### Step 8: Session capture (after posting)

After reporting, resolve `TASK_DIR` and append to `$TASK_DIR/SESSION.md` (if found):

```bash
TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null || echo "")
```

```
[TIME] crew-pr-resolver: N applied / N adapted / N rejected / N deferred
```

### Auto-journal

Regardless of `TASK_DIR` (PRs not built through the pipeline have none), store an immutable observation (no prompt — passive) from the threads and verdicts, via `~/.agent/bin/mem.py journal add --title "PR review: <PR title>" --tags <tags> --repo <scope>` with the prose on stdin (heredoc). Write 1-3 paragraphs in plain prose. Focus on what *you* learned from the feedback — not what you applied mechanically:
- What the reviewer caught that you missed, and why it matters / what pattern it reveals
- What to watch for next time in similar code (omit if nothing genuinely new)

Skip writing when no thread yielded a non-derivable lesson. On non-zero exit print `warning: memory unavailable` and continue.

> Next: run `crew commit` to commit resolved changes.

## Notes

- **Always use `--json` with `gh` commands** — `gh pr view`, `gh pr list`, etc. without `--json` open a pager that freezes the VS Code terminal. Every `gh` call must either use `--json` or pipe through `| cat`.

- `isOutdated: true` means the code has changed since the comment — these are surfaced in the Outdated Threads section of the report, not actioned
- Multiple comments in a thread = read all for context before deciding (first is the suggestion, later are follow-ups and discussion)
- Never apply a suggestion that defeats the purpose of the original code
- GraphQL is the only reliable way to get thread resolution state + both ID types in a single round-trip
