# Probing a question

Step 4 detail for `crew-pr-resolver`. Loaded whenever a thread is unsettled.

## Why probe

A thread you cannot settle is not a thread you should hand to the author. It is a suspicion: the comment
points at something real and you cannot see whether it is. Guessing in either direction is the failure —
applying a wrong fix costs a review round trip, and resolving a doubtful thread tells the reviewer
"handled" about work nobody stood behind.

A probe is how a suspicion becomes evidence. Run the code the thread is about, look at what it actually
produces, and let the measurement set the score. The question is a heuristic; the probe is the check.

The trigger is the one in Step 4 of the agent file — a verdict below `ACTED_CONFIDENCE`, one that
would render `Ask`, or one you are torn between. What the uncertainty is about decides the probe,
not whether you run one:

- **what the code does at runtime** — a rendered expression, a value after a skipped step, a query's
  rows, a branch taken. Write a throwaway test that exercises the entry point the thread names.
- **what a fixture or test actually asserts** — run that one test file and read the failure or pass.
- **what a helper or schema accepts** — call it from a throwaway test with the input the thread
  describes, and observe the result or the error.
- **what a caller does with the value** — a repro through the public entry point, not an inspection of
  the implementation.

Skip the probe only when it is infeasible, not when it is inconvenient: a missing dependency tree, a
harness needing a live cluster, a package that cannot build. Say which, keep the thread `Ask`, and name
what would have to change to settle it.

## The probe

The smallest throwaway artifact that answers the one question — in the package that owns the behavior,
through the interface the thread names, not a copy of its internals.

1. Write it beside the package's existing tests, named so it cannot be mistaken for a real one.
2. Reproduce the thread's conditions exactly: the skipped step, the absent field, the empty result, the
   unusual input. One question per probe; a probe answering three settles none of them clearly.
3. Run it with the package's own command under whatever elevation the harness needs. A sandbox refusal
   is a probe failure, not a result.
4. Record the command, the expression or call, and the observed output verbatim.
5. **Delete it, whatever happened.** Deletion is not the last step of the happy path: a run that could
   not run the probe, was interrupted, or stopped after three attempts deletes it too. Then confirm
   `git status --porcelain` is clean before the report — that check, not a path-scoped diff, is what
   catches a leftover file and any snapshot or cache directory a test run wrote.

The probe is the only write evaluation makes, and it is gone before the report in every outcome. No
tracked file changes, and no untracked one either.

## Scoring on the measurement

The observed value is the evidence, so it sets the score: a measurement that confirms the comment
outranks a reading of the code that merely suggests it, and one that refutes it settles the thread as
`Reject`. A thread left at 1-2 after a probe means the probe did not answer the question the verdict
turns on — narrow it, or say plainly that it cannot be settled here.

## Reporting it

The reply quotes the expression or call, the observed output, and the command, then draws the
conclusion the thread asked for. State the limit in the same breath: a probe covers the case it built,
not the whole workflow, the stored record, or the call path around it.

- **Probe confirms the problem** → verdict `Apply`, the measurement supporting the edit. A probe worth
  keeping is proposed as a test inside that edit, through the approval gate — never left behind.
- **Probe refutes it** → verdict `Reject`, scored on the measurement, the reply citing the observed
  value instead of reasoning about what the code would do.
- **Probe cannot run or does not settle it** → verdict stays `Ask`, and the reply says what stopped it.
  "Cannot verify here" with its reason is an answer; a guess dressed as a measurement is not.
