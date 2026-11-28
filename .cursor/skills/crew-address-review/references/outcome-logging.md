# Outcome logging and memory candidates

Step 3b. Input: `TASK_DIR` from Step 1 (empty for none). Applies to both modes whenever a review run
directory exists. A spec review has one:
`pipeline.md` sets `REVIEW_ROOT` for self, changes, spec, and idea reviews, and `persist` writes
`REVIEW.spec.md` beside `SPEC.md`, while `normalize` assigns every finding a fingerprint. Skip this
step only when `$TASK_DIR` is empty and no review directory exists, and say so.

Run it after the user responds and before any edit. `<review-dir>` is the newest directory under
`$TASK_DIR/review/` (it holds the persona outputs and `candidates.json`). If `$TASK_DIR` is empty or
that directory does not exist, skip outcome logging and say so; never invent a path. If
`findings.json` is missing, run `~/.agent/bin/crew-review-findings.py normalize
<review-dir>/candidates.json --output <review-dir>/findings.json` and take `<id>`, `<persona>`, and
`<label>` from it.

Every finding this run decides on gets one line: applied, adapted, and rejected alike. A finding it
leaves alone gets none. Recording is part of making the decision, not a report on it, because the
answer is only known at that moment: a later pass that reconstructs it either guesses or skips.
**Record a raised score with the decision that raised it.** Step 2 may raise a 1-2 finding's
`confidence` when the read settles what it doubted, and the raise is only evidence while it stays
attached to the read: pass the final score with the outcome (`--confidence <n> --confidence-from
<old> --validation "<the read>"`) so the record keeps the score the finding was acted on under, not
the score it arrived with. The raise is refused without that sentence, and an unchanged
pair is refused outright, so a raise that cannot name its evidence cannot be logged. A `Needs Input`
row keeps the score it arrived with. The `+2` ceiling is
[consolidation](~/.cursor/agents/crew-reviewer/references/consolidation.md)'s to state and no gate
enforces it, so a raise above it passes every check.

For each finding the user did not approve (a Needs Input row left unanswered counts as `deferred`):

```bash
~/.agent/bin/crew-tool.py review-record-outcome <review-dir> <id> <persona> <label> \
  <rejected|deferred|skipped> <reason> [--memory-id <id> ...]
```

It appends immutable JSONL records to `<review-dir>/../outcomes.jsonl`. Log `fixed` only in Step 4,
after the edit lands. Then run `outcomes --acted` with every fingerprint this run decided on, as
"Before the summary" below describes, and treat exit 1 as an incomplete run.

## Before the summary

Before the summary, prove the record is complete. Collect the fingerprints of every finding this run
applied, adapted, or rejected, pass them to `--acted`, and let the command decide:

```bash
~/.agent/bin/crew-review-findings.py outcomes --review-dir <review-dir> --acted <id> <id> ...
```

It prints the counts and exits 1 naming any acted fingerprint with no outcome. Exit 1 fails the
summary: a summary that omits a decision reads as a clean pass over a corpus missing the evidence.
Findings left alone need no record and are not passed to `--acted`.

Draft zero to three durable, evidence-backed memory candidates into `~/.agent/memory/.inbox/` from the
accepted outcomes, including the rejected-finding candidates below; nothing derivable from the
changed files or the review record, and nothing imported. Show their titles (or `none`) with the
summary and ask nothing: they wait for the approval point `memory-capture.mdc` names.

## Rejected-finding candidates

For each rejected finding, draft a repo-scoped `feedback` candidate into `.inbox/` titled `reviewer
false positive: <finding>`. `<slug>` is the finding title reduced to `[a-z0-9-]`, at most 60
characters; `<repository-key>` is the bare upstream repository name (for example `el-capitan`), not the
checkout directory:

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
retrieval-ready claim and a `**Don't apply when:**` condition. A file in `.inbox/` is only a draft even
when its frontmatter says `status: active`; do not import it. These candidates count toward Step 4's
limit. For cited memory ids, run `crew-mem.py cite <ids> --outcome misled`; on exit 2 print `warning:
memory unavailable`.
