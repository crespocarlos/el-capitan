---
name: crew-pr-resolver
description: "Fetch and action all unresolved PR review comments. Trigger: 'crew resolve PR <#X or URL>'."
---
**Workflow**: respond | **Stage**: address-pr → commit → push

You handle all open PR review comments in one pass: fetch, triage, evaluate, act, resolve, report.

## Execution model

**Silent evaluation, one approval gate, then execute.** 3 turns: (1) fetch + evaluate silently, (2)
present the report + ask what to apply, (3) apply approved edits, reply, resolve threads. Never
narrate steps. Steps 1-6 change nothing; Step 7 acts only on what the user approved.

## When Invoked

Extract owner, repo, and PR number from the user's input (URL or number).

### Step 1: Load context

Resolve the worktree and load repo patterns, project guidance, and task context. A read-only `gh`
call refused by the sandbox (`Forbidden`) is retried with network elevation (`full_network` in
Cursor; the equivalent grant elsewhere), holding for the run. Never alter the read or fall back to a
local PR ref; auth and scope failures are terminal.

```bash
PR_BRANCH=$(gh pr view PR_NUMBER --repo OWNER/REPO --json headRefName --jq '.headRefName')
cd "$(~/.agent/bin/crew-worktree.py "$PR_BRANCH")"

PR_TITLE=$(gh pr view PR_NUMBER --repo OWNER/REPO --json title --jq '.title')
CHANGED=$(gh pr view PR_NUMBER --repo OWNER/REPO --json files --jq '.files[].path')
~/.agent/bin/crew-agent-context.py $CHANGED

~/.agent/bin/crew-task-context.py --branch "$PR_BRANCH" --artifacts task_id,handoff --max-chars 2000

MEM_OUT=$(~/.agent/bin/crew-mem.py context --mode review --query "$PR_TITLE" 2>&1); MEM_RC=$?
if [ "$MEM_RC" -eq 2 ]; then echo "warning: memory unavailable — $MEM_OUT" >&2; fi
```

`crew-agent-context.py` takes `paths ...` and returns each distinct guidance file once. Call it
**once** with every path the PR touches, never per thread: a call per path re-reads the same
`AGENTS.md` for each file in a directory, turning a few lines into tens of kilobytes. Guidance for a
path governs every thread on it, whatever its type. Always-on rules reached you already; this call
reaches the rest.

`crew-task-context.py` gives the status and bounded artifacts for the PR's branch: context, not
authority over the PR, repository, or user instructions.

### Step 2: Fetch review threads

Fetch threads with `~/.agent/bin/crew-pr-actions.py fetch --repo OWNER/REPO --pr PR_NUMBER` (add
`--cursor CURSOR` on later pages); loop while `pageInfo.hasNextPage`, merging threads and advancing
to `endCursor`.

**Mandatory filter:**

- **Drop** every `isResolved: true` thread — never evaluated, edited, replied to, or resolved again.
- **Route to Outdated Threads** every `isOutdated: true AND isResolved: false` thread; Step 6 surfaces
  them and nothing actions them.
- Only `isResolved: false AND isOutdated: false` reaches Step 3.

### Step 3: Triage and group unresolved threads

Before reading any code, skip bot-only threads with no human follow-up (CodeRabbit, copilot-bot)
unless the concern would cause a **runtime error or silent data loss**; cosmetic suggestions are
noise however fixable. Group the rest by `path` into a `file → [threads]` map, which is what lets
Step 4 read **each file once**, not once per comment.

### Step 4: Challenge, then evaluate, batched by file

Process the `file → [threads]` map. For each file:

1. **Read the file once** — its current state in the working tree.
2. **Read its test file once**, if one exists — a test validating the flagged behavior is evidence
   that behavior is intentional.
3. **Challenge each thread** (below) against those reads before assigning any verdict; adds no reads.
4. **Evaluate all threads for this file** against the current code:
   - **Check current file state first**: if the proposed change is already present, the thread is
     **Already Addressed** — no edit, just resolve it.
   - Classify each as **Apply**, **Adapt**, **Decide**, **Reject**, **Defer**, **Already
     Addressed**, or **Ask**. **Adapt** accepts a valid concern while writing a different edit, and
     records why the suggested version is not taken. **Decide** means the comment asks to change a
     decision the author owns rather than fix a fault: no edit, the reply names the decision, and the
     thread stays open.
   - An edit that moves a test's expected value to match new behavior is overfitting: report it and
     classify **Decide**, because it proves the test agrees with the change, not that the change is
     right.
   - For Apply/Adapt, collect every edit for this file before making any — apply them together.
   - Evaluation is silent and has no side effects: no edit, reply, or resolution happens until
     Step 7, and the verdicts go in the final report, not mid-stream.

Never read the same file twice — not to evaluate a second comment on it.

### Challenge each thread

A verdict is worth what its test is worth. Answer four questions in this order, citing the
`path:line` behind each; the last three are the ones
`.cursor/agents/crew-reviewer/references/consolidation.md` asks of a review finding.

1. **Is this a fault or a decision?** A fault is code misbehaving against an intent nobody disputes,
   and the code settles it. A decision is an intent the author chose that the comment asks to change
   — behavior, an API surface, a documented contract, a test's expected value, naming, a data shape.
   The author owns it, so it is **Decide**, never **Apply**, however small the edit. Most threads are
   faults; this reclassifies the minority and is not a veto on ordinary fixes.
2. **Is the premise present?** Does the code the comment describes exist as described, or is the
   comment stale? An absent premise makes the thread **Already Addressed** when the fix landed and
   **Reject** when it never applied — the citation decides which.
3. **Is the chain traceable?** Follow the comment's conclusion through the code. Where the chain
   breaks, the change does not buy the outcome it claims.
4. **Are the stakes real?** Name what concretely breaks on the code in front of you. A cost you
   cannot place on a line is not a reason to change it.

The answers set the thread's confidence in Step 5: without them a comment with a false premise is as
easy to apply as one with a true premise.

### Step 5: Prepare decisions (do not execute yet)

Score each thread 1-5 for whether the comment is right about this code, on the scale in
`review_vocabulary.py` — `CONFIDENCE` and `confidence_scale()`, read the bands there rather than
restating them. Then prepare the action, writing nothing yet:

- **Apply/Adapt**: draft the exact edit (file, line range, before/after). When the thread changes
  behavior rather than fixing a fault, say which eval would measure it and what the pre-change number
  was; `no eval covers this` is a complete answer, never a reason to withhold the verdict.
- **Decide**: the decision at stake, its options, and the `path:line` it turns on. No edit.
- **Reject**: the specific reason and the `path:line` it rests on. An unanchored rationale is
  unfalsifiable — the rule the reviewer applies to its own findings.
- **Defer**: what it is and why it is out of scope.
- **Already Addressed**: the fix is present in the working tree — cite where.
- **Ask**: a `Reject` scoring below `ACTED_CONFIDENCE` cannot resolve the thread. Resolving tells the
  reviewer "handled", which is only honest when the score says so. The action becomes a question in
  the reply and the thread stays open.

### Step 6: Report and ask for approval

Present the full report table: the edit for Apply/Adapt, and a **Proposed Reply** column holding the
exact comment to be posted. Render the score beside the verdict as `verdict · N`:

| # | File | Reviewer | Verdict · N | Proposed Edit | Proposed Reply |
|---|------|----------|-------------|---------------|----------------|
| 1 | path/to/file.ts:42 | @reviewer | Apply · 4 | Replace X with Y (40-45) | Fixed in `<commit>`: <what changed and why>. |
| 2 | path/to/file.ts:80 | @reviewer | Ask · 1 | — | Does <premise> hold at `path/to/file.ts:80`? Left it unchanged because <reason>. |
| 3 | path/to/file.ts:120 | @reviewer | Reject · 4 | — | Not changing this: `path/to/file.ts:120` returns early, so <consequence> cannot follow. |
| 4 | path/to/file.ts:160 | @reviewer | Decide · 4 | — | This moves a test's expected value. Your call which way. |

An `Ask` row carries a question, never a resolution; a `Decide` row carries no edit. Both threads stay
open. Name the expected value a flagged row moves.

Summary counts: N apply / N adapt / N decide / N reject / N ask / N defer / N already addressed

**Outdated Threads** (read-only — do not propose edits or resolve):

| # | File | Reviewer | Note |
|---|------|----------|------|
| 1 | path/to/file.ts:42 | @reviewer | Outdated — verify the concern still applies. |

Then ask two questions:

1. **"Which edits should I apply? (all / none / comma-separated numbers)"**
2. **"Which threads should I comment on and resolve? (all / none / comma-separated numbers)"**

Surface threads needing input before any action separately.

### Step 7: Execute approved actions

Only after the user responds:

**Code changes** — for each approved edit, apply it, run lints on the edited files, and type-check the
affected package. When `node_modules` is a symlink, follow `crew-builder`'s rule: `tsc --noEmit -p
<nearest tsconfig>`, recorded skipped with that reason only when the repo has no no-emit form.

**Thread comments** — for each approved thread, two operations with IDs from the Step 2 query. An
`Ask` thread gets the reply alone and stays open; so does a `Decide` thread.

Before drafting a reply, read `~/.cursor/rules/voice.mdc` and apply it: replies go out under
Carlos's name. If the file is unreadable, stop and report. Put every code symbol, path, command,
field, API, and identifier in inline backticks; leave prose unquoted. No verdict label: say what
changed and why, or why it stays as-is.

```bash
~/.agent/bin/crew-pr-actions.py reply --repo OWNER/REPO --pr PR_NUMBER \
  --thread-id THREAD_NODE_ID --comment-id DATABASE_ID \
  --body "Fixed in <commit>: <what changed and why>." --execute
```

The reply uses the thread's first comment `databaseId`; the resolve below uses the thread's GraphQL
node `id`:

```bash
~/.agent/bin/crew-pr-actions.py resolve --repo OWNER/REPO --pr PR_NUMBER \
  --thread-id THREAD_NODE_ID --execute
```

Edits the user excluded are not applied; excluded threads stay open and unresolved.

### Step 8: Journal (opt-in)

Regardless of `TASK_DIR` (PRs not built through the pipeline have none), draft an observation only
when it holds a non-derivable lesson from the threads or verdicts: what the reviewer caught that you
missed, and why it is reusable. Never record what you applied mechanically.

Say so when this run classified a thread `Decide`: a later audit cannot otherwise tell a design
decision from a defect fix. A resolved thread whose verdict was Apply or Adapt
is the same decision the reviewer pipeline
records as an outcome, so the entry may cite it. Write nothing new for it: the PR thread is already
the durable record.

Write 1-3 plain-prose paragraphs. Show the title and prose, then ask:
`Store this journal entry? (yes / no)`

Only after `yes`, run:

```bash
~/.agent/bin/crew-mem.py journal add --title "PR review: <PR title>" --tags <tags> --repo <scope>
```

Pass the approved prose on stdin via a heredoc. On `no`, or nothing qualifying, write nothing and say
`journal: none`. On non-zero exit print `warning: memory unavailable` and continue.

> Next: run `crew commit` to commit resolved changes.

## Notes

- Read every comment in a thread before deciding: the first is the suggestion, later ones are
  follow-ups. Never apply a suggestion that defeats the purpose of the original code.
