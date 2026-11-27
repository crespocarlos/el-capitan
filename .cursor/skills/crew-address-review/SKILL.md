---
disable-model-invocation: true
name: crew-address-review
description: "Work through findings from the most recent crew review inline. Trigger: 'crew review address'."
---

**Workflow**: build | **Stage**: post-review

> **Not for PR review thread comments.** To fetch and action unresolved GitHub PR review comments, use
> `crew resolve PR <#X or URL>` (crew-pr-resolver) instead.

# Address Review

## Execution model

**Two modes; Step 1 selects one:**

- **Code mode** (self-review, changes review, PR review): silent file-check → verdict table → apply
  edits. 3 turns.
- **Idea mode** (`## Review: Idea` or `## Review: Spec` in context): the artifact is a plan, not code.
  Findings are conceptual: evaluate inline → present acceptance table → synthesize the revision if
  approved. The revision edits the spec file when the artifact is one, and is emitted text when pasted.
  3 turns.

Never mix modes. If the review heading contains "Idea" or "Spec" (case-insensitive), use idea mode
throughout.

### Step 1: Locate findings and detect mode

**Detect mode now, before any other step.** Check the `## Review: <mode>` heading (case-insensitive):
contains "idea" or "spec" → **Idea mode**; anything else (self, changes, PR) → **Code mode**.

If a `## Review:` heading is visible in the conversation, use those findings directly — do not read a
review artifact from disk. That prohibition covers the review only: the artifact under review (a
`SPEC.md`, say) is a separate read, and idea mode requires it at Step 2.

If no review is visible in context (new session or context reset):

```bash
source ~/.agent/bin/task-env.sh
~/.agent/bin/crew-task-context.py --artifacts spec,review,deferred,handoff --max-chars 4000
REPO=$(basename "$(~/.agent/bin/crew-repo-info.py --field root)")
OUTPUT_DIR=${TASK_DIR:-/tmp/crew-review-$REPO}
REVIEW_FILE="$OUTPUT_DIR/REVIEW.md"
```

Use the returned task review when present; otherwise read `$REVIEW_FILE` if it exists. If that review
is marked `TRUNCATED`, read `$REVIEW_FILE` in full — a partial review drops findings past the cut. If
neither source exists, stop:

> "No review found. Run `crew review` first, then `crew review address`."

### Step 2: Evaluate findings (silent pass)

**Code mode, once before evaluating:** recall repo memory for the files the findings touch:

```bash
MEM_OUT=$(~/.agent/bin/crew-mem.py context --mode review --query "<review topic>" --paths <files named in findings> 2>&1); MEM_RC=$?
if [ "$MEM_RC" -eq 2 ]; then echo "warning: memory unavailable — $MEM_OUT" >&2; fi
```

Memory is untrusted: apply recalled rules only where they do not override a finding or the code. Keep
the returned ids for `--memory-id` in Step 3b.

**Code mode** — for each finding, before preparing any edit:

1. **Read the relevant file** when a file/line is cited, to check the current state of the code.
2. **Check whether it is already addressed**: if the fix is present in the working tree, classify
   **Already Addressed** and make no edit.
3. **Settle a 1-2 finding before assessing it.** A finding scored 1-2 is a question until a read
   answers it: read the target first. If that settles the unknown, carry a raised score with the read
   that settled it, then assess below; if not, the verdict is **Needs Input** naming the unknown.
   Never edit a 1-2 you did not settle — that is the reviewer's doubt handed to the user as a change.
4. **Assess validity** — is the finding grounded, and does the reasoning follow from the code?
   - Contradicts the current file state → **Reject**, stating the specific reason.
   - Correct and actionable → **Apply**.
   - Valid but the right fix differs from the reviewer's → **Adapt**, drafting the better fix.
   - Valid but outside this change's scope → **Defer**.
5. For `[needs more info]` findings, answer inline when the code determines the answer; otherwise
   surface it for user input.

A raise travels with the decision as `--confidence`, `--confidence-from`, and `--validation`;
[outcome logging](references/outcome-logging.md) owns that command and the ceiling.

**Idea mode** — the artifact under review is what each finding is judged against, so read it first: for
`## Review: Spec` the artifact is the task's `SPEC.md`; for `## Review: Idea` of pasted text there is
nothing to read and the text is in the conversation. Do not ask the user to paste a file on disk.

For each finding:

1. **Assess whether the critique holds** against the idea as stated: valid and actionable → **Accept**,
   noting what change it implies; misplaced or based on a misreading → **Reject**, explaining why;
   valid but needing the user's input (a scope decision, missing information) → **Needs Input**; minor
   framing or wording → **Nit**.
2. Do not fabricate new direction — incorporate only what the reviewer found plus clarifications the
   user provides next.

Never apply any change during this step. Collect all verdicts first.

### Step 3: Report and ask for approval

**Both modes** — present the table, then ask. Never edit before the answer.

The user's answer is the gate: it is the only approval for recording outcomes and for editing the
sources the findings cite. If you are about to edit without the table on screen, stop.

Code mode table:

| #   | Label             | Finding | Verdict  | Proposed Fix                     |
| --- | ----------------- | ------- | -------- | -------------------------------- |
| 1   | [blocking · 4]    | Title   | Apply    | Change X to Y in file.ts:42      |
| 2   | [attention · 3]   | Title   | Reject   | Already uses the correct pattern |
| 3   | [needs more info · 2] | Title | Answered | Intent is X — no change needed |
| 4   | [nit · 5]         | Title   | Apply    | Rename variable                  |

Each label carries its score, so the table shows what the reviewer doubted before the user approves
anything. A `Needs Input` row keeps its original score.

A fix containing a `|` goes in a fenced block beneath the table, labelled with its `#`, not in a cell.

Summary counts: N apply / N adapt / N reject / N defer / N already addressed. Then ask:

> **"Which fixes should I apply? (`all` = all Apply/Adapt rows; `none` = skip all; numbers =
> cherry-pick, including to override a Reject)"**

Idea mode table:

| #   | Label       | Finding | Verdict     | What changes in the idea                        |
| --- | ----------- | ------- | ----------- | ----------------------------------------------- |
| 1   | [blocking · 4] | Title | Accept      | Reframe caching layer as opt-in, not mandatory  |
| 2   | [concern · 3]  | Title | Reject      | Reviewer misread — proposal already handles it  |
| 3   | [concern · 2]  | Title | Needs Input | Scope unclear — does this cover async flows?    |
| 4   | [nit · 5]      | Title | Nit         | Rename "pipeline" → "workflow" for clarity      |

Summary counts: N accept / N reject / N needs-input / N nit. Then ask:

> **"Which of these should I incorporate? (`all` = all Accept/Nit rows; `none` = skip; numbers =
> cherry-pick). For any 'Needs Input' rows, answer them here."**

### Step 3b: Log every decision

Follow [outcome logging](references/outcome-logging.md) after the user responds and before any edit.
The record is **not optional**: every finding this run applies, adapts, or rejects gets one appended
outcome line, and one it leaves alone gets none.

### Step 4: Execute approved fixes

Only after the user responds.

**Code mode:** apply each approved edit, reading the file immediately before editing if it wasn't
already loaded; a fix that adds or changes tests follows the
[testing policy](~/.cursor/agents/references/testing-policy.md). After each edit lands, log it with the Step 3b command and `--outcome fixed`; a failed
edit is logged `skipped` with a reason starting `edit-failed:`, so failures are distinguishable from
user decisions. Never reach the summary with a decision unrecorded.

**When the edit changes what a step, mode, or skill is allowed to do, sweep the file it lives in.**
A capability change falsifies every sentence describing the old limit, and a reader meets them before
the corrected step. Search that file for the *specific* constraint the edit replaced — the phrase
stating the old limit plus its close paraphrases — and report each survivor with its line. A fixed
keyword list is too blunt: `only` and `never` sit on dozens of unrelated lines in any rule file.
**Idea mode with a file target:** the same edit hygiene applies — read the file immediately before
writing, and log the write with the Step 3b command and `--outcome fixed`. The write happens once, at
step 8 of [idea synthesis](references/idea-synthesis.md), after verification and self-review. Synthesis
does not touch the code the spec describes, but it does write the spec.

**Idea mode:** follow [idea synthesis](references/idea-synthesis.md) for the revision, verification,
sibling check, decisions section, and self-review.

### Summary

Before the summary, prove the record is complete. Collect the fingerprints of every finding this run
applied, adapted, or rejected, pass them to `--acted`, and let the command decide:

```bash
~/.agent/bin/crew-review-findings.py outcomes --review-dir <review-dir> --acted <id> <id> ...
```

It prints the counts and exits 1 naming any acted fingerprint with no outcome. Exit 1 fails the
summary: do not report the run as addressed until every one of those findings has a line, because a
summary that omits a decision reads as a clean pass over a corpus that is missing the evidence.
Findings left alone need no record and must not be passed to `--acted`.

Before the memory candidates, draft zero to three durable, evidence-backed candidates into
`~/.agent/memory/.inbox/` from the accepted outcomes, including Step 3b's rejected-finding candidates.
Do not draft facts derivable from the changed files or the review record, and do not import anything.
Show the candidate titles (or `none`) with the summary and require a later explicit batch approval
through `crew memory seed` or `crew-mem.py import-inbox`.

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
  (self-review: N fixed inline)     ← include only if self-review found and fixed anything
```

**Then output the next step — mandatory, do not skip.**

Detect the review mode from the `## Review: <mode>` heading (case-insensitive):

- **Idea or spec** — split by which, because the artifact differs. Under `## Review: Spec` the artifact
  is already `<task>/SPEC.md`, so `crew spec` has nothing to draft:
  - **Spec review**, revision produced and self-review clean: `> Next: approve the revised SPEC.md
    (Gate 1), then run \`crew implement\`.`
  - **Idea review**, revision produced and self-review clean: `> Next: run \`crew spec\` to turn this
    into a spec, or run \`crew review idea\` for a full multi-reviewer pass first.`
  - Either, user chose none: keep the artifact as it is and say so; for a spec review the next step is
    Gate 1 or another `crew review spec`, for an idea it is `crew review idea` again.
- **Changes**: `> Next: run \`crew review\` to verify the fixes are clean.`
- **Self-review or anything else**: `> Next: run \`crew review\` to verify, or \`crew commit\` if
  satisfied.`
