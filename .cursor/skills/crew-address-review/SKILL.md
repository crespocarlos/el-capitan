---
name: crew-address-review
description: "Work through findings from the most recent crew review inline. Trigger: 'crew review address'."
---

**Workflow**: build | **Stage**: post-review

> **Not for PR review thread comments.** To fetch and action unresolved GitHub PR review comments, use `crew resolve PR <#X or URL>` (crew-pr-resolver) instead.

# Address Review

## Execution model

**Two modes — detect before starting:**

- **Code mode** (self-review, changes review, PR review): silent file-check → verdict table → apply edits. 3 turns.
- **Idea mode** (`## Review: Idea` or `## Review: Spec` in context): no files to edit — findings are conceptual. Evaluate inline → present acceptance table → synthesize revised idea if approved. 3 turns.

Never mix modes. If the review heading contains "Idea" or "Spec" (case-insensitive), use idea mode throughout.

## When Invoked

### Step 1: Locate findings and detect mode

**Detect mode now, before any other step.** Check the `## Review: <mode>` heading in context (case-insensitive):
- Contains "idea" or "spec" → **Idea mode**
- Anything else (self, changes, PR, etc.) → **Code mode**

Carry this mode through Steps 2–4 without re-detecting.

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

**Code mode:** For each finding, before preparing any edits:

1. **Read the relevant file** (if a specific file/line is cited) — check the current state of the code
2. **Check if already addressed**: if the finding's fix is already present in the working tree, classify as **Already Addressed** — no edit needed
3. **Assess validity**: is the finding grounded? Does the reasoning follow from the actual code/artifact?
   - If the finding contradicts the current file state, classify as **Reject** — state the specific reason
   - If the fix is correct and actionable, classify as **Apply**
   - If the finding is valid but the right fix is different from what the reviewer suggested, classify as **Adapt** — draft the better fix
   - If the finding is valid but touches scope outside this change, classify as **Defer**
4. For `[needs more info]` findings: answer the question inline if you can determine the answer from the code; otherwise surface it for user input

**Idea mode:** No files to read. For each finding:

1. **Assess whether the critique holds**: does the reviewer's concern actually apply to the idea as stated?
   - If the concern is valid and actionable, classify as **Accept** — note what change to the idea it implies
   - If the concern is misplaced or based on a misreading, classify as **Reject** — explain why
   - If the concern is valid but needs the user's input to resolve (e.g. scope decision, missing info), classify as **Needs Input**
   - If the concern is minor framing or wording, classify as **Nit**
2. Do not fabricate new direction — only incorporate what the reviewer found plus any clarifications the user provides in the next step

Never apply any change during this step. Collect all verdicts first.

### Step 3: Report and ask for approval

**Code mode** — present the verdict table:

| #   | Label             | Finding | Verdict  | Proposed Fix                     |
| --- | ----------------- | ------- | -------- | -------------------------------- |
| 1   | [blocking]        | Title   | Apply    | Change X to Y in file.ts:42      |
| 2   | [attention]       | Title   | Reject   | Already uses the correct pattern |
| 3   | [needs more info] | Title   | Answered | Intent is X — no change needed   |
| 4   | [nit]             | Title   | Apply    | Rename variable                  |

Summary counts: N apply / N adapt / N reject / N defer / N already addressed

Then ask:

> **"Which fixes should I apply? (`all` = all Apply/Adapt rows; `none` = skip all; numbers = cherry-pick, including to override a Reject)"**

**Idea mode** — present the acceptance table:

| #   | Label      | Finding | Verdict      | What changes in the idea                        |
| --- | ---------- | ------- | ------------ | ----------------------------------------------- |
| 1   | [blocking] | Title   | Accept       | Reframe caching layer as opt-in, not mandatory  |
| 2   | [concern]  | Title   | Reject       | Reviewer misread — proposal already handles it  |
| 3   | [concern]  | Title   | Needs Input  | Scope unclear — does this cover async flows?    |
| 4   | [nit]      | Title   | Nit          | Rename "pipeline" → "workflow" for clarity      |

Summary counts: N accept / N reject / N needs-input / N nit

Then ask:

> **"Which of these should I incorporate? (`all` = all Accept/Nit rows; `none` = skip; numbers = cherry-pick). For any 'Needs Input' rows, answer them here."**

### Step 4: Execute approved fixes

Only after the user responds.

**Code mode:** Apply each approved edit. Read the file immediately before editing if it wasn't already loaded.

After all edits are applied, print the summary and the mode-aware next step (see below).

**Idea mode:** Do not edit any files. Instead:

1. If the user chose `none`, skip synthesis entirely — go straight to the summary.
2. Collect all accepted/nit items plus any user answers to Needs Input items.
3. Locate the original idea text — it is in the session conversation (the pasted text or the output of the prior `crew review idea` turn). If the original idea is not recoverable from context (scrolled out or session reset), ask: `"I can't locate the original idea text in context — please paste it and I'll produce the revised version."` Then wait.
4. Produce a **revised idea** that incorporates all accepted changes. Match the original structure and heading levels. Do not add new sections; do not remove content unless a finding specifically called it out. Present it inline as a clean proposal under a heading like `## Revised Idea`.

After revision (or if the user chose `none`), print the summary.

**Summary (both modes):**

Code mode:
```
Review addressed:
  ✓ [blocking]        N fixed (N rejected, N already addressed)
  ✓ [attention]       N fixed (N rejected, N deferred)
  — [needs more info] N answered inline / N need user input
  — [nit]             N fixed / N skipped
```

Idea mode:
```
Idea updated:
  ✓ [blocking]  N incorporated (N rejected)
  ✓ [concern]   N incorporated (N rejected, N deferred to user)
  — [nit]       N incorporated / N skipped
```

**Then output the next step — this is mandatory, do not skip.**

Detect the review mode from the `## Review: <mode>` heading in context (case-insensitive match):

- **Idea** (heading contains "idea" or "spec"): if revision was produced, say `> Revised idea above. Run \`crew review idea\` again to re-evaluate, or \`crew spec\` to turn it into a spec.` If the user chose none, say `> No changes applied. Run \`crew review idea\` again or proceed with the original idea.`
- **Changes** (heading contains "changes"): `> Next: run \`crew review\` to verify the fixes are clean.`
- **Self-review / anything else**: `> Next: run \`crew review\` to verify, or \`crew commit\` if satisfied.`
