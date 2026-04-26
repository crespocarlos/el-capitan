---
name: crew-address-review
description: "Work through findings from the most recent crew review inline. Trigger: 'crew review address'."
---

**Workflow**: build | **Stage**: post-review

# Address Review

## Execution model

**Silent evaluation, then approval, then execute.** 3 turns: (1) locate + evaluate findings silently, (2) present full verdict table + ask what to apply, (3) apply approved fixes. Never narrate steps or start editing during evaluation.

## When Invoked

### Step 1: Locate findings

Check if a `## Review:` heading is visible in the current session conversation. If yes, use those findings directly — do not read any file.

If no review is visible in context (new session or context reset):

```bash
TASK_DIR=$(python3 ~/.agent/bin/resolve-task-dir.py 2>/dev/null)
REPO=$(basename $(git rev-parse --show-toplevel))
OUTPUT_DIR=${TASK_DIR:-/tmp/crew-review-$REPO}
REVIEW_FILE="$OUTPUT_DIR/REVIEW.md"
```

If `$REVIEW_FILE` exists, read it. If neither source is available, stop:

> "No review found. Run `crew review` first, then `crew review address`."

### Step 2: Evaluate findings (silent pass)

For each finding, **before preparing any edits**:

1. **Read the relevant file** (if a specific file/line is cited) — check the current state of the code
2. **Check if already addressed**: if the finding's fix is already present in the working tree, classify as **Already Addressed** — no edit needed
3. **Assess validity**: is the finding grounded? Does the reasoning follow from the actual code/artifact?
   - If the finding contradicts the current file state, classify as **Reject** — state the specific reason
   - If the fix is correct and actionable, classify as **Apply**
   - If the finding is valid but the right fix is different from what the reviewer suggested, classify as **Adapt** — draft the better fix
   - If the finding is valid but touches scope outside this change, classify as **Defer**
4. For `[needs more info]` findings: answer the question inline if you can determine the answer from the code; otherwise surface it for user input

Never apply any change during this step. Collect all verdicts first.

### Step 3: Report and ask for approval

Present the full verdict table:

| #   | Label             | Finding | Verdict  | Proposed Fix                     |
| --- | ----------------- | ------- | -------- | -------------------------------- |
| 1   | [blocking]        | Title   | Apply    | Change X to Y in file.ts:42      |
| 2   | [attention]       | Title   | Reject   | Already uses the correct pattern |
| 3   | [needs more info] | Title   | Answered | Intent is X — no change needed   |
| 4   | [nit]             | Title   | Apply    | Rename variable                  |

Summary counts: N apply / N adapt / N reject / N defer / N already addressed

Then ask:

> **"Which fixes should I apply? (`all` = all Apply/Adapt rows; `none` = skip all; numbers = cherry-pick, including to override a Reject)"**

### Step 4: Execute approved fixes

Only after the user responds — apply each approved edit. Read the file immediately before editing if it wasn't already loaded.

After all edits are applied, print:

```
Review addressed:
  ✓ [blocking]        N fixed (N rejected, N already addressed)
  ✓ [attention]       N fixed (N rejected, N deferred)
  — [needs more info] N answered inline / N need user input
  — [nit]             N fixed / N skipped

> Next: run `crew review` to verify, or `crew commit` if satisfied.
```
