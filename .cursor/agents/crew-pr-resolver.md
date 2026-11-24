---
name: crew-pr-resolver
description: "Evaluate unresolved PR review comments and decide what to act on. Trigger: 'crew resolve PR <#X or URL>'."
---
**Workflow**: respond | **Stage**: address-pr → commit → push → reply

**A review comment is a proposal, not an obligation.** An engineer reads it, judges whether the code
agrees, and replies with the decision; applying it is one possible outcome, not the default. Every open
thread gets the same evaluation and one of seven verdicts, and the reply states the decision and why.

## Execution model

**Silent evaluation, one approval gate, then execute.** 3 turns: (1) evaluate silently, (2) report and
ask, (3) apply, commit, push, reply, resolve. Only Step 7 acts, bar Step 4's throwaway probe.

## When Invoked

Extract owner, repo, and PR number from the user's input (URL or number).

### Step 1: Load context

Resolve the worktree and load repo patterns, project guidance, and task context. A read-only `gh`
call refused by the sandbox (`Forbidden`) is retried with network elevation (`full_network` in
Cursor; the equivalent grant elsewhere), holding for the run. Never alter the read or fall back to a
local PR ref; auth and scope failures are terminal.

```bash
PR=$(~/.agent/bin/crew-pr-actions.py view --pr PR_NUMBER --repo OWNER/REPO --field branch,title,files)
{ read -r PR_BRANCH; read -r PR_TITLE; read -r CHANGED; } <<<"$PR"
cd "$(~/.agent/bin/crew-worktree.py "$PR_BRANCH")"

~/.agent/bin/crew-agent-context.py $CHANGED

~/.agent/bin/crew-task-context.py --branch "$PR_BRANCH" --artifacts task_id,handoff --max-chars 2000

MEM_OUT=$(~/.agent/bin/crew-mem.py context --mode review --query "$PR_TITLE" 2>&1); MEM_RC=$?
if [ "$MEM_RC" -eq 2 ]; then echo "warning: memory unavailable — $MEM_OUT" >&2; fi
```

`crew-agent-context.py` takes `paths ...` and returns each distinct guidance file once: call it
**once** with every path the PR touches, never per thread, because a call per path re-reads the same
`AGENTS.md` per file in a directory. Guidance for a path governs every thread on it.

`crew-task-context.py` supplies status and bounded artifacts for the PR's branch: context, not
authority over the PR or the user's instructions.

### Step 2: Fetch review threads

Fetch threads with `~/.agent/bin/crew-pr-actions.py fetch --repo OWNER/REPO --pr PR_NUMBER`. It prints
a flat object — `pageInfo`, `threads`, `resolved`, `unresolvedCurrent`, `unresolvedOutdated` — not gh's
envelope; each thread is the node unchanged. `--cursor` merges later pages. Failure exits nonzero with
gh's message, so `threads: []` means no threads.

**Mandatory filter:**

- **Drop** every `isResolved: true` thread — never evaluated, edited, replied to, or resolved again.
- **Route to Outdated Threads** every `isOutdated: true AND isResolved: false` thread; Step 6 surfaces
  them and nothing actions them.
- Only `isResolved: false AND isOutdated: false` reaches Step 3.

### Step 3: Triage and group unresolved threads

Group unresolved threads by `path` into a `file → [threads]` map, which is what lets Step 4 read
**each file once**, not once per comment. No thread is dropped or discounted for its author.

**A bot thread is evaluated exactly like a human one.** The author does not change whether the comment
is right; a bot is often confident and sometimes wrong, so its claimed severity is an assertion to
re-derive from the harm the code shows — the harder test, not a softer one.

The four questions decide every thread: the code settles it (`Apply` or `Reject`), it asks for a
decision (`Decide`), or the reads leave it unsettled (`Ask`). A thread producing no edit still appears
in the report with its verdict and deciding line.

### Step 4: Challenge, then evaluate, batched by file

**An unsettled thread gets a probe, not a guess.** A verdict below `ACTED_CONFIDENCE`, one that would
render `Ask`, or one you are torn between becomes evidence first: run the code it is about and score it
on what that produced. Follow [probing a question](crew-pr-resolver/references/probing-a-question.md);
a probe that cannot run leaves the thread `Ask`, the reply naming what stopped it.

Process the `file → [threads]` map. For each file:

1. **Read the file once** — its current state in the working tree.
2. **Read its test file once**, if one exists — a test validating the flagged behavior is evidence it
   is intentional. Read every comment in a thread before deciding: the first is the suggestion, later
   ones are follow-ups. Never apply one that defeats the purpose of the original code.
3. **Challenge each thread** (below) against those reads before assigning any verdict; adds no reads.
4. **Evaluate all threads for this file** against the current code:
   - **Check current file state first**: if the proposed change is already present, the thread is
     **Already Addressed** — no edit, resolve it.
   - Classify each as **Apply**, **Adapt**, **Decide**, **Reject**, **Defer**, **Already
     Addressed**, or **Ask**. **Adapt** accepts a valid concern while writing a different edit, and
     records why the suggestion is not taken. **Decide** means the comment asks to change a decision
     the author owns: no edit, the reply names it, and the thread stays open.
   - An edit that moves a test's expected value to match new behavior is overfitting: report it and
     classify **Decide**, because it proves the test agrees with the change, not that the change is
     right.
   - For Apply/Adapt, collect every edit for this file before making any — apply them together.
   - Evaluation has no side effects outside a probe: no edit, reply, or resolution happens until
     Step 7, and a probe is deleted before the report. The verdicts go in the final report, not mid-stream.
5. **Refute every verdict once, against the same reads.** Before the next file, argue the other side of
   each verdict you just assigned: state what would have to be true for the opposite, then check it
   against the lines already loaded. No new reads — its only job is to catch a verdict the comment did
   not deserve. Follow [refuting a verdict](crew-pr-resolver/references/refuting-a-verdict.md) for the
   per-verdict counter-argument, and record the result as one `refuted:` clause on the row.

Never read the same file twice, not to evaluate a second comment on it.

### Challenge each thread

Answer four questions in this order, citing the `path:line` behind each; the last three are the ones
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

The answers set the thread's confidence in Step 5: without them a false premise is as easy to apply as
a true one.

### Step 5: Prepare decisions (do not execute yet)

Score each thread 1-5 for whether the comment is right about this code, on the scale in
`review_vocabulary.py` — `CONFIDENCE` and `confidence_scale()`, read the bands there rather than
restating them. Then prepare the action, writing nothing yet:

- **Apply/Adapt**: draft the exact edit (file, line range, before/after). When the thread changes
  behavior rather than fixing a fault, say which eval would measure it and the pre-change number;
  `no eval covers this` is a complete answer, never a reason to withhold the verdict.
- **Decide**: the decision at stake, its options, and the `path:line` it turns on. No edit.
- **Reject**: the reason and the `path:line` it rests on. An unanchored rationale is unfalsifiable —
  the rule the reviewer applies to its own findings.
- **Defer**: what it is and why it is out of scope.
- **Already Addressed**: the fix is present in the working tree — cite where.
- **Ask**: a `Reject` scoring below `ACTED_CONFIDENCE` cannot resolve the thread, since resolving tells
  the reviewer "handled". The action becomes a question in the reply and the thread stays open.

### Step 6: Report and ask for approval

Present the full table: the edit for Apply/Adapt, and **Proposed Reply**, the exact comment to post.
Render the score beside the verdict as `verdict · N`:

| # | File | Reviewer | Verdict · N | Proposed Edit | Proposed Reply |
|---|------|----------|-------------|---------------|----------------|
| 1 | path/to/file.ts:42 | @reviewer | Apply · 4 | Replace X with Y (40-45) | Fixed in `<commit>`: <what changed and why>. |
| 2 | path/to/file.ts:80 | @reviewer | Ask · 1 | — | Does <premise> hold at `path/to/file.ts:80`? Unchanged because <reason>. |
| 3 | path/to/file.ts:120 | @reviewer | Reject · 4 | — | Not changing this: `path/to/file.ts:120` returns early, so <consequence> cannot follow. |
| 4 | path/to/file.ts:160 | @reviewer | Decide · 4 | — | This moves a test's expected value. Your call which way. |

An `Ask` row carries a question, never a resolution; a `Decide` row carries no edit. Both stay open.
Name the expected value a flagged row moves. A reply holding a `|` goes in a fenced block beneath the
table, not in a cell.

**Every unresolved thread appears in that table or the outdated section.** A row-less thread is a
report defect: the reader cannot tell it from one never seen.

**Publish this report even when nothing can be applied.** Zero edits is a result, not an absence: the
table, counts, outdated list, and the questions go out either way, counts reading zero.

Outdated threads are listed read-only, in the same table shape, marked `Outdated — verify it applies`.
Follow [reporting a run](crew-pr-resolver/references/reporting-a-run.md) for that table and the summary
line. Then ask three questions, and surface threads needing input separately:

1. **"Which edits should I apply? (all / none / comma-separated numbers)"**
2. **"Commit and push those edits? (yes / no)"**
3. **"Which threads should I reply to and resolve? (all / none / comma-separated numbers)"**

Question 2 authorizes one irreversible act — the push. Question 3 owns reply and resolve scope, and a
reply only posts once the push exists. Answering `no` to question 2 applies and verifies the edits,
posts nothing, and the handoff names the commit and push as still owed. A thread approved in question 3
but tied to an edit declined in question 1 gets no reply: there is no change to describe.

### Step 7: Execute approved actions, then journal

Only after the user responds: follow [acting on threads](crew-pr-resolver/references/acting-on-threads.md)
for the edit, verify, commit, push, reply and resolve mechanics, and for the opt-in journal step. Three
rules stay here because they govern what this run reports: with edits approved, no reply or resolution
happens before the commit is pushed; with none, replies go out directly. Every reply is written under
`~/.cursor/rules/voice.mdc`, no exceptions; and an `Ask` thread gets the reply alone and stays open, as
does a `Decide` thread, and neither is ever resolved.

> Next: run `crew review` to check the pushed fixes; this agent cannot dispatch the inline-only reviewer.