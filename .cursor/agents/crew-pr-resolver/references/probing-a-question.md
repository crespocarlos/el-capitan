# Probing a question

Step 4 detail for `crew-pr-resolver`. Loaded whenever a thread is unsettled.

The probe lifecycle — why it beats a guess, its three triggers, the four shapes of uncertainty, the
five steps, deletion, scoring, and reporting — is held once in
[probing an unsettled claim](../../references/probing.md). Read it there; this file keeps only what a
thread changes.

## What a thread changes

The claim under test is a review comment, and what a probe has to measure is whether the comment is
right about **this** code. So the artifact exercises the entry point the comment names, in the package
that owns the behavior, and the observed value decides between `Apply` and `Reject` — not whether the
author should have written it differently. A probe answers the fault question, never the decision
question: an intent the author chose stays `Decide` however the code behaves.

This mode's two extra trigger bounds, beside the shared score-of-3 rule: a verdict below
`ACTED_CONFIDENCE` and one that would render `Ask`. Both are resolver terms — the first is the floor a
thread must clear to be applied or rejected, the second is the verdict for a thread the reads leave
open — and neither means anything to a reviewer, which is why they live here and not in the shared
file. A thread that would render `Ask` gets a probe before it becomes a question.

## The clean-tree rule is stricter here

The resolver runs in a worktree it owns, so the shared compare tightens into this: after deleting the
probe, `git status --porcelain` must be clean — empty output — because this worktree started that way
and a leftover file is the run's own defect. That check, not a path-scoped diff, is what makes the
tree clean before the report. A reviewer's tree already holds the edits under review, so there the
compare is against the reading taken before the probe; both rest on the same command and only the
expected reading differs.

## Reporting a thread

The reply quotes the expression or call, the observed output, and the command, then gives the verdict:

- **Probe confirms the comment** → verdict `Apply`, the measurement supporting the edit. A probe worth
  keeping is proposed as a test inside that edit, through the approval gate — never left behind.
- **Probe refutes it** → verdict `Reject`, scored on the measurement, the reply citing the observed
  value instead of reasoning about what the code would do.
- **Probe cannot run or does not settle it** → verdict stays `Ask`, and the reply says what stopped it.
  "Cannot verify here" with its reason is an answer; a guess dressed as a measurement is not.
