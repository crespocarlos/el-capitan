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

## The probe writes nothing here

The resolver's analysis is a read-only subagent, so the shared lifecycle's write and delete steps do
not apply: a probe runs the code or tests already in the tree, with commands that write no file. One
that needs a written artifact is not run; the thread stays `Ask` and the plan names that probe, so the
main session can raise it with the user. `git status --porcelain` must still read empty after the
probe, as it did before.

## Reporting a thread

The reply carries what the shared file's "Reporting it" names, then gives the verdict:

- **Probe confirms the comment** → verdict `Apply`, the measurement supporting the edit (a probe
  worth keeping becomes a test in that edit, as the shared file says).
- **Probe refutes it** → verdict `Reject`, scored on the measurement; the reply cites the observed
  value.
- **Probe cannot run or does not settle it** → verdict stays `Ask`, and the reply says what stopped it.
