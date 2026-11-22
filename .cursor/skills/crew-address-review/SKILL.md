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
  approved. The revision is an edit to the spec file when the artifact is one, and emitted text when it
  is pasted. 3 turns.

Never mix modes. If the review heading contains "Idea" or "Spec" (case-insensitive), use idea mode
throughout.

### Step 1: Locate findings and detect mode

**Detect mode now, before any other step.** Check the `## Review: <mode>` heading (case-insensitive):
contains "idea" or "spec" → **Idea mode**; anything else (self, changes, PR) → **Code mode**. Carry it
through Steps 2–4 without re-detecting.

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
2. **Check whether it is already addressed**: if the fix is already present in the working tree,
   classify as **Already Addressed** and make no edit.
3. **Assess validity** — is the finding grounded, and does the reasoning follow from the code?
   - Contradicts the current file state → **Reject**, stating the specific reason.
   - Correct and actionable → **Apply**.
   - Valid but the right fix differs from the reviewer's → **Adapt**, drafting the better fix.
   - Valid but outside this change's scope → **Defer**.
4. For `[needs more info]` findings, answer inline when the code determines the answer; otherwise
   surface it for user input.

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

The harness asks before this flow records anything: `.claude/settings.json` carries a
`permissions.ask` rule for `Edit`/`Write` under the task directory and for
`crew-review-findings.py`, so writing the outcome log or the review artifacts prompts for approval,
and the prompt arrives with the table still on screen. There is no marker file and no state to clear:
nothing can be left behind to block an unrelated edit later.

That prompt does not cover edits to the source files the findings cite — a permission rule cannot see
which flow is running. Those are authorized by the answer to the question below, and only by it. If you
are about to edit without having shown the table, stop.

Code mode table:

| #   | Label             | Finding | Verdict  | Proposed Fix                     |
| --- | ----------------- | ------- | -------- | -------------------------------- |
| 1   | [blocking]        | Title   | Apply    | Change X to Y in file.ts:42      |
| 2   | [attention]       | Title   | Reject   | Already uses the correct pattern |
| 3   | [needs more info] | Title   | Answered | Intent is X — no change needed   |
| 4   | [nit]             | Title   | Apply    | Rename variable                  |

Summary counts: N apply / N adapt / N reject / N defer / N already addressed. Then ask:

> **"Which fixes should I apply? (`all` = all Apply/Adapt rows; `none` = skip all; numbers =
> cherry-pick, including to override a Reject)"**

Idea mode table:

| #   | Label      | Finding | Verdict      | What changes in the idea                        |
| --- | ---------- | ------- | ------------ | ----------------------------------------------- |
| 1   | [blocking] | Title   | Accept       | Reframe caching layer as opt-in, not mandatory  |
| 2   | [concern]  | Title   | Reject       | Reviewer misread — proposal already handles it  |
| 3   | [concern]  | Title   | Needs Input  | Scope unclear — does this cover async flows?    |
| 4   | [nit]      | Title   | Nit          | Rename "pipeline" → "workflow" for clarity      |

Summary counts: N accept / N reject / N needs-input / N nit. Then ask:

> **"Which of these should I incorporate? (`all` = all Accept/Nit rows; `none` = skip; numbers =
> cherry-pick). For any 'Needs Input' rows, answer them here."**

### Step 3b: Log every decision

Follow [outcome logging](references/outcome-logging.md) after the user responds and before any edit.
The record is **not optional**: every finding this run applies, adapts, or rejects gets one appended
outcome line, and a finding it leaves alone gets none. Recording where the decision is made is the
only point the answer is known — asking later is what left 704 of 719 measured findings unrecorded.

### Step 4: Execute approved fixes

Only after the user responds. The ask rule is what holds the gate, so an edit that the harness did
not prompt for means the rule is missing — say so rather than proceeding silently.

**Code mode:** apply each approved edit, reading the file immediately before editing if it wasn't
already loaded. After each edit lands, log it with the Step 3b command and `--outcome fixed`; if an
edit fails, log `skipped` with a reason starting `edit-failed:`, so failures are distinguishable from
user decisions. Do not continue to the summary with a decision unrecorded.

**When the edit changes what a step, mode, or skill is allowed to do, sweep the file it lives in.** A
capability change falsifies every sentence describing the old limit, and a reader meets them before the
corrected step. After the approved edits land, search that file for the *specific* constraint the edit
replaced — the phrase stating the old limit plus its close paraphrases — and report each surviving
sentence with its line. A fixed keyword list is too blunt: `only` and `never` appear on dozens of
unrelated lines in any rule file, and a report of unrelated hits is one a reader skips. This is idea
mode's sibling sweep applied to the instructions themselves.

**Idea mode with a file target:** the same edit hygiene applies — read the file immediately before
writing, and log the write with the Step 3b command and `--outcome fixed`. The write happens once, at
step 8 of [idea synthesis](references/idea-synthesis.md), after verification and self-review; nothing
is written before then. Synthesis, not implementation: it does not touch the code the spec describes,
but it does write the spec.

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
