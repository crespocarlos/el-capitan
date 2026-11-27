# Probing an unsettled claim

The lifecycle of a probe, held once. A consumer's own reference adds only what its mode changes and
links here for the rest.

## Why probe

A claim you cannot settle is not one you should hand to a human as a question. It is a suspicion: it
points at something real and you cannot see whether it is. Guessing in either direction is the
failure — a wrong fix costs a round trip, and a doubted finding resolved as "handled" tells the
author work was done that nobody stood behind.

A probe is how a suspicion becomes evidence. Run the code the claim is about, look at what it actually
produces, and let the measurement set the score: the question is a heuristic, the probe is the check.

## The trigger

Three bounds, and any one of them sends a claim to a probe: a score below 3 — the floor a
`[blocking]` or `[attention]` needs — or a call you are genuinely torn between. A consumer's own
reference may add a bound its mode defines. What the uncertainty is about decides the probe, not
whether you run one:

- **what the code does at runtime** — a rendered expression, a value after a skipped step, a query's
  rows, a branch taken. Write a throwaway test that exercises the entry point the claim names.
- **what a fixture or test actually asserts** — run that one test file and read the failure or pass.
- **what a helper or schema accepts** — call it from a throwaway test with the input the claim
  describes, and observe the result or the error.
- **what a caller does with the value** — a repro through the public entry point, not an inspection
  of the implementation.

Skip the probe only when it is infeasible, not when it is inconvenient: a missing dependency tree, a
harness needing a live cluster, a package that cannot build. Say which, keep the claim open, and name
what would have to change to settle it.

## The probe

The smallest throwaway artifact that answers the one question — in the package that owns the
behavior, through the interface the claim names, not a copy of its internals.

1. Write it beside the package's existing tests, named so it cannot be mistaken for a real one.
2. Reproduce the claim's conditions exactly: the skipped step, the absent field, the empty result,
   the unusual input. One question per probe; a probe answering three settles none of them clearly.
3. Run it with the package's own command under whatever elevation the harness needs. A sandbox
   refusal is a probe failure, not a result.
4. Record the command, the expression or call, and the observed output verbatim.
5. **Delete it, whatever happened.** Deletion is not the last step of the happy path: a run that
   could not run the probe, was interrupted, or stopped after three attempts deletes it too. Then
   compare `git status --porcelain` with the reading taken before the probe: identical output is what
   makes the tree clean before the report, and that compare — not a path-scoped diff, and not an
   empty reading — is what catches a leftover file and any snapshot or cache directory a test run
   wrote. The tree you probe in already holds the edits under review, so identical output is the
   rule and emptiness is not.

The probe is the only write evaluation makes, and it is gone before the report in every outcome. No
tracked file changes, and no untracked one either.

## Scoring on the measurement

The observed value is the evidence, so it sets the score in either direction: a measurement that
confirms the claim outranks a reading of the code that merely suggests it, and one that refutes it
settles the claim the other way. The upward ceiling is consolidation's — at most 2, a discipline the
pass keeps because no gate enforces it. A claim still at 1-2 after a probe means the probe did not
answer the question the score turns on — narrow it, or say plainly that it cannot be settled here.

## Reporting it

The reply quotes the expression or call, the observed output, and the command, then draws the
conclusion the claim asked for. State the limit in the same breath: a probe covers the case it built,
not the whole workflow, the stored record, or the call path around it.

- **Probe confirms the problem** → keep the claim, the measurement supporting the edit, and record
  `probe: confirmed` beside the score. A probe worth keeping is proposed as a test inside that edit,
  through the approval gate — never left behind.
- **Probe refutes it** → drop the claim, or relabel it, scored on the measurement and citing the
  observed value instead of reasoning about what the code would do. Record `probe: refuted`: it is the
  only outcome that may lower a score, and it may never sit beside one that rose.
- **Probe cannot run or does not settle it** → the claim keeps its score and states what stopped it, as
  a question: a `[blocking]` or `[attention]` becomes `[needs more info]` naming the blocked probe, and
  no run that did not execute is ever reported as though it had. "Cannot verify here" with its reason
  is an answer; a guess dressed as a measurement is not.

## Saving the reply

In self and changes mode `persist` refuses an emitted `[needs more info]` or 1-2 finding until the
probe is on record. Pipe the worker's reply, unedited, into `crew-review-findings.py save-out
--review-dir <review-dir> --persona probe --harness <name>` (add `--agent-id` when known): it writes
`probe.out.md` with the provenance record `persist` checks, so a hand-written or edited file is
refused. When the probe cannot run here, the report says `probe: skipped <reason>: <detail>` instead,
`<reason>` one of `no-runtime`, `no-network`, `pr-only`, `external-service`; any other reason is
refused, and every unsettled finding stays `[needs more info]`.

## Who probes

A persona cannot run code: `readonly: true` is the only tool restriction Cursor honours, and a persona
that writes would edit the tree mid-review. So the orchestrator probes on its behalf. After the
verification read, it collects every finding still unsettled in that review — each one with a score
below 3, or one the reviewer is genuinely torn between — and dispatches **one** `reviewer-probe`
run carrying all of them, never one dispatch per claim. One run keeps the tree state simple and makes
the tree comparison mean something; a claim that arrives later joins a second run rather than
reopening the first.

Give the worker each claim, its `path:line`, and the question a read could not answer. The worker
returns the command, the observed output, and an outcome per claim; the orchestrator sets the score
from that evidence and records that outcome as `probe`. A claim nobody could probe is not a claim
nobody dispatched: name it and what blocked it. Surface the worker's closing tree check to the user,
because a run that did not restore the tree is that run's own defect and nobody else can act on it.

**PR mode never dispatches `reviewer-probe`.** A PR review has no checkout and its mode forbids making
one, so there is nothing for the worker to run against and the local tree is not the artifact under
review. A PR-mode finding that stays unsettled keeps `[needs more info]` and names the blocked probe —
what it could not run and what would unblock it — instead of quoting an observation from a tree the PR
does not describe.
