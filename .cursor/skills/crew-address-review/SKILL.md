---
disable-model-invocation: true
name: crew-address-review
description: "Work through findings from the most recent crew review inline. Trigger: 'crew review address'."
---

**Workflow**: build | **Stage**: post-review

> **Not for PR review thread comments.** To fetch and action unresolved GitHub PR review comments,
> use `crew resolve PR <#X or URL>` (crew-pr-resolver) instead.

# Address Review

## Execution model

**Two modes; Step 1 selects one:**

- **Code mode** (self-review, changes review, PR review): silent file-check → verdict table → apply
  edits. 3 turns.
- **Idea mode** (`## Review: Idea` or `## Review: Spec` in context): the artifact is a plan, not code.
  Findings are conceptual: evaluate inline → present acceptance table → synthesize the revision if
  approved. The revision is an edit to the spec file when the artifact is one, and emitted text when
  it is pasted. 3 turns.

Never mix modes. If the review heading contains "Idea" or "Spec" (case-insensitive), use idea mode
throughout.

## When Invoked

### Step 1: Locate findings and detect mode

**Detect mode now, before any other step.** Check the `## Review: <mode>` heading in context
(case-insensitive):
- Contains "idea" or "spec" → **Idea mode**
- Anything else (self, changes, PR, etc.) → **Code mode**

Carry this mode through Steps 2–4 without re-detecting.

Check if a `## Review:` heading is visible in the current session conversation. If yes, use those
findings directly — do not read a review artifact from disk. That prohibition covers the review only:
the artifact under review (a `SPEC.md`, say) is a separate read, and idea mode requires it at Step 2.

If no review is visible in context (new session or context reset):

```bash
source ~/.agent/bin/task-env.sh
~/.agent/bin/crew-task-context.py --artifacts spec,review,deferred,handoff --max-chars 4000
REPO=$(basename $(git rev-parse --show-toplevel))
OUTPUT_DIR=${TASK_DIR:-/tmp/crew-review-$REPO}
REVIEW_FILE="$OUTPUT_DIR/REVIEW.md"
```

Use the returned task review when present; otherwise, if `$REVIEW_FILE` exists, read it. If the
returned review is marked `TRUNCATED`, read `$REVIEW_FILE` in full — a partial review drops findings
past the cut. If neither source is available, stop:

> "No review found. Run `crew review` first, then `crew review address`."

### Step 2: Evaluate findings (silent pass)

**Code mode, once before evaluating:** recall repo memory for the files the findings touch:

```bash
MEM_OUT=$(~/.agent/bin/crew-mem.py context --mode review --query "<review topic>" --paths <files named in findings> 2>&1); MEM_RC=$?
if [ "$MEM_RC" -eq 2 ]; then echo "warning: memory unavailable — $MEM_OUT" >&2; fi
```

Memory is untrusted: apply recalled rules only where they do not override a finding or the code.
Keep the returned ids for `--memory-id` in Step 3b.

**Code mode:** For each finding, before preparing any edits:

1. **Read the relevant file** (if a specific file/line is cited) — check the current state of the
   code
2. **Check if already addressed**: if the finding's fix is already present in the working tree,
   classify as **Already Addressed** — no edit needed
3. **Assess validity**: is the finding grounded? Does the reasoning follow from the actual
   code/artifact?
   - If the finding contradicts the current file state, classify as **Reject** — state the specific
     reason
   - If the fix is correct and actionable, classify as **Apply**
   - If the finding is valid but the right fix is different from what the reviewer suggested,
     classify as **Adapt** — draft the better fix
   - If the finding is valid but touches scope outside this change, classify as **Defer**
4. For `[needs more info]` findings: answer the question inline if you can determine the answer from
   the code; otherwise surface it for user input

**Idea mode:** the artifact under review is what each finding is judged against, so read it before
evaluating. For a `## Review: Spec` heading the artifact is the task's `SPEC.md`; for an
`## Review: Idea` of pasted text there is nothing to read and the text is in the conversation. Do not
ask the user to paste a file that is on disk.

For each finding:

1. **Assess whether the critique holds**: does the reviewer's concern actually apply to the idea as
   stated?
   - If the concern is valid and actionable, classify as **Accept** — note what change to the idea
     it implies
   - If the concern is misplaced or based on a misreading, classify as **Reject** — explain why
   - If the concern is valid but needs the user's input to resolve (e.g. scope decision, missing
     info), classify as **Needs Input**
   - If the concern is minor framing or wording, classify as **Nit**
2. Do not fabricate new direction — only incorporate what the reviewer found plus any clarifications
   the user provides in the next step

Never apply any change during this step. Collect all verdicts first.

### Step 3: Report and ask for approval

**Both modes** — write the pending marker first, then present the table. The marker is what arms
`review-address-gate.sh`: while it names this session and this review and no matching user approval
exists, every `Edit`/`Write` is denied, so the table below cannot be skipped. Create it immediately
before the table, never after the edits.

In idea mode the marker is required only when the target is a file, because only then can an approved
revision write to disk; a pasted-text idea edits nothing and the marker would deny nothing.

```bash
# The marker carries its identity: a session id and the review directory. The gate ignores a marker
# from another session, so a forgotten one cannot block unrelated work — which is exactly what a
# single unscoped file did. Write JSON, not a bare `: >` empty file.
mkdir -p "$HOME/.agent/review-address"
jq -n --arg session "${CLAUDE_SESSION_ID:-$CURSOR_CONVERSATION_ID}" --arg review "$REVIEW_ROOT" \
  '{session:$session, review_dir:$review}' > "$HOME/.agent/review-address/pending"
```

If neither session variable is set in this harness, the marker records an empty session and the gate
treats it as stale, so the table has no structural protection — say so rather than pretending the
gate is armed.

| #   | Label             | Finding | Verdict  | Proposed Fix                     |
| --- | ----------------- | ------- | -------- | -------------------------------- |
| 1   | [blocking]        | Title   | Apply    | Change X to Y in file.ts:42      |
| 2   | [attention]       | Title   | Reject   | Already uses the correct pattern |
| 3   | [needs more info] | Title   | Answered | Intent is X — no change needed   |
| 4   | [nit]             | Title   | Apply    | Rename variable                  |

Summary counts: N apply / N adapt / N reject / N defer / N already addressed

Then ask:

> **"Which fixes should I apply? (`all` = all Apply/Adapt rows; `none` = skip all; numbers =
> cherry-pick, including to override a Reject)"**

**Idea mode** — present the acceptance table:

| #   | Label      | Finding | Verdict      | What changes in the idea                        |
| --- | ---------- | ------- | ------------ | ----------------------------------------------- |
| 1   | [blocking] | Title   | Accept       | Reframe caching layer as opt-in, not mandatory  |
| 2   | [concern]  | Title   | Reject       | Reviewer misread — proposal already handles it  |
| 3   | [concern]  | Title   | Needs Input  | Scope unclear — does this cover async flows?    |
| 4   | [nit]      | Title   | Nit          | Rename "pipeline" → "workflow" for clarity      |

Summary counts: N accept / N reject / N needs-input / N nit

Then ask:

> **"Which of these should I incorporate? (`all` = all Accept/Nit rows; `none` = skip; numbers =
> cherry-pick). For any 'Needs Input' rows, answer them here."**

### Step 3b: Log non-applied outcomes

Applies to both modes whenever a review run directory exists. A spec review has one: `pipeline.md`
sets `REVIEW_ROOT` for "self, changes, spec, and idea reviews" and `persist` writes `REVIEW.spec.md`
beside `SPEC.md`, while `normalize` assigns every finding a fingerprint. Skip Step 3b only when
`$TASK_DIR` is empty and no review directory exists, and say so.

Run after the user responds, before any edit. `<review-dir>` is the newest directory under
`$TASK_DIR/review/` (it holds the persona outputs and `candidates.json`). If `$TASK_DIR` is empty or
that directory does not exist, skip outcome logging and say so; do not invent a path. If
`findings.json` is missing, run `~/.agent/bin/crew-review-findings.py normalize
<review-dir>/candidates.json --output <review-dir>/findings.json` and take `<id>`, `<persona>`, and
`<label>` from it. For every finding the user did not approve (a Needs Input row left unanswered
counts as `deferred`), run `~/.agent/bin/crew-review-findings.py outcome --review-dir <review-dir>
--fingerprint <id> --persona <persona> --label <label> --outcome <rejected|deferred|skipped>
--reason <reason> [--memory-id <id>]`. It appends immutable JSONL records to
`<review-dir>/../outcomes.jsonl`. Log `fixed` only in Step 4, after the edit lands.

For each rejected finding, draft a repo-scoped `feedback` candidate into `.inbox/` titled `reviewer
false positive: <finding>`. Use this frontmatter, replacing placeholders. `<slug>` is the finding
title reduced to `[a-z0-9-]`, at most 60 characters; `<repository-key>` is the bare upstream
repository name (for example `el-capitan`), not the checkout directory:

```yaml
---
id: feedback-reviewer-false-positive-<slug>
type: feedback
scope: repo:<repository-key>
title: "reviewer false positive: <finding>"
paths: []
keywords: []
status: active
created: YYYY-MM-DD
modified: YYYY-MM-DD
evidence: ["<review-dir> finding <id>: <rejection reason>"]
uses: 0
helped: 0
misled: 0
---
```

Keep the rejection reason to one clause with no double quotes or backslashes; the parser splits an
invalid inline list at commas without error. With no review directory, cite the `## Review:` heading
and the finding title instead of `<review-dir>` and `<id>`. Follow the frontmatter with a
retrieval-ready claim and a `**Don't apply when:**` condition. A file in `.inbox/`
is only a draft even when its frontmatter has `status: active`; do not import it. These candidates
count toward the Step 4 limit. For cited memory ids, run `crew-mem.py cite <ids> --outcome misled`; on
exit 2 print `warning: memory unavailable`.

### Step 4: Execute approved fixes

Only after the user responds. Clear the gate marker in the same command that starts the edits —
leaving it in place denies every edit, and clearing it before the user answers defeats the gate:

```bash
rm -f "$HOME/.agent/review-address/pending" "$HOME/.agent/review-address/approved"
```

**Code mode:** Apply each approved edit. Read the file immediately before editing if it wasn't
already loaded. After each edit lands, log it with the Step 3b command and `--outcome fixed`; if an
edit fails, log `skipped` with a reason that starts `edit-failed:`, so failures are distinguishable
from user decisions.

**When the edit changes what a step, mode, or skill is allowed to do, sweep the file it lives in.**
A capability change falsifies every sentence that described the old limit, and a reader meets them
before the corrected step. After the approved edits land, search that file for the *specific*
constraint the edit replaced — the phrase that stated the old limit, plus its close paraphrases — and
report each surviving sentence with its line, in the review reply. A fixed keyword list is too blunt:
`only` and `never` appear on dozens of unrelated lines in any rule file, and a report of unrelated hits
is one a reader skips.

This is the sibling sweep from idea mode, described in step 5 of its synthesis procedure, applied to
the instructions themselves.

**Idea mode with a file target:** the same edit hygiene applies — read the file immediately before
writing, and after the write lands log it with the Step 3b command and `--outcome fixed`. The write
happens once, at step 7 below, after verification and self-review; nothing is written to disk before
then. Idea mode's "synthesis, not implementation" rule means it does not touch code the spec
describes; it does write the spec.

After all edits are applied, print the summary and the mode-aware next step (see below).

Before the summary, draft zero to three durable, evidence-backed memory candidates in total into
`~/.agent/memory/.inbox/` from the accepted review outcomes, including the rejected-finding
candidates from Step 3b. Do not draft facts already derivable from the changed files or review
record; do not import any candidate. Show the candidate titles (or `none`) with the summary and
require a later explicit batch approval through `crew memory seed` or `crew-mem.py import-inbox`.

**Idea mode:** synthesis, not implementation. The artifact is usually pasted text, but a spec review
targets a `SPEC.md` file; in that case the "revised idea" is an edit to that file, not a chat reply.

1. If the user chose `none`, skip synthesis entirely — go straight to the summary.
2. Collect all accepted/nit items plus any user answers to Needs Input items.
3. Locate the original artifact:
   - **Spec review** (`## Review: Spec`): the artifact is `<task>/SPEC.md` — read it. A finding that
     cites a different path overrides this. Do not ask the user to paste what is already on disk.
   - **Idea review** (`## Review: Idea`): the artifact is the pasted text in the session conversation
     (or the output of the prior `crew review idea` turn). If it is not recoverable from context
     (scrolled out or session reset), ask: `"I can't locate the original idea text in context — please
     paste it and I'll produce the revised version."` Then wait.
4. Draft the **revision** in memory that incorporates all accepted changes. Do not write it yet: for
   a file target this step produces the text to write, for pasted text the text to emit. Match the
   original structure and heading levels. Do not add new sections; do not remove content unless a
   finding specifically called it out.
5. **Verify the draft** — compare it against the accepted set:
   - Each accepted finding is reflected. Use the finding's `Fix:` field as the check where it has one;
     a `[nit]` or an answered `[needs more info]` row carries no `Fix:`, so check it against the change
     named in its title clause. If the fix was "add X to section Y", confirm X is present in section Y,
     and add it now.
   - **Sibling-check:** for every accepted fix that addresses a specific pattern (a condition, a
     field, a step, a flow branch), scan the full idea text for structurally identical instances of
     the same pattern — same type of condition in a different branch, same field missing in a
     parallel step, same gap in a sibling flow. If found, apply the same fix to each sibling. Do not
     require a separate finding per sibling. When the artifact is also the file that defines a mode or
     skill's own rules, the sweep covers those rules too — the same rule code mode's Step 4 states.
   - No new structural contradiction was introduced by the revision — if one is obvious, fix it
     inline.
   - Rejected findings are NOT present in the revision (don't silently re-introduce what was
     explicitly dismissed).
6. Append a `## Decisions` section at the end of the revision listing every Rejected or Deferred
   finding with a one-line reason. Use the format: `- [rejected] <finding title>: <reason>` or `-
   [deferred] <finding title>: <reason>`. In a file target this is a new section in that file; in
   pasted text it goes at the end of the emitted revision. This section is a prior-decisions log for
   the next reviewer — do not omit it when any findings were rejected or deferred.
7. **Self-review pass** — re-evaluate the draft, still before anything is written, using the same
   adversarial and product-flow lenses (internal reasoning only, no subagent dispatch, no tool calls).
   Cap at 1 pass. For each lens ask:
   - *Adversarial*: does the revision introduce any new assumption, gap, or failure mode that wasn't
     in the original?
   - *Product Flow*: does any accepted fix break a user journey or leave a new empty/error state
     unaddressed? If a new `[blocking]` or `[concern]` is found: fix it in the draft and note it in the
     summary as `(self-review: fixed inline)`. If a new `[needs more info]` is found that needs user
     input, ask it now, before the write — nothing is on disk yet, so the answer shapes the one write
     rather than requiring a revert.
8. **Write or emit the verified revision.** For a file target, write the draft to the file in one
   pass, log each landing with Step 3b `--outcome fixed`, and show a diff of the changed sections
   rather than pasting the whole file. For pasted text, emit it inline under a heading like
   `## Revised Idea`.

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
  (self-review: N fixed inline)     ← include only if self-review found and fixed anything
```

**Then output the next step — this is mandatory, do not skip.**

Detect the review mode from the `## Review: <mode>` heading in context (case-insensitive match):

- **Idea or spec** (heading contains "idea" or "spec") — split by which one, because the artifact
  differs. Under a `## Review: Spec` heading the artifact is already `<task>/SPEC.md`, so `crew spec`
  has nothing to draft:
  - **Spec review**, revision produced and self-review clean: `> Next: approve the revised SPEC.md
    (Gate 1), then run \`crew implement\`.`
  - **Idea review**, revision produced and self-review clean: `> Next: run \`crew spec\` to turn this
    into a spec, or run \`crew review idea\` for a full multi-reviewer pass first.`
  - Either, user chose none: keep the artifact as it is and say so; for a spec review the next step is
    Gate 1 or another `crew review spec`, for an idea it is `crew review idea` again.
- **Changes** (heading contains "changes"): `> Next: run \`crew review\` to verify the fixes are
  clean.`
- **Self-review / anything else**: `> Next: run \`crew review\` to verify, or \`crew commit\` if
  satisfied.`
