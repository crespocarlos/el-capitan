---
disable-model-invocation: true
name: crew-debug
description: "Find the root cause of a failure with an evidence-first loop before fixing it. Trigger: 'crew debug <symptom, failing test, error, or log>'."
---

**Workflow**: any | **Stage**: debug

# Systematic Debugging

Find the cause, then fix it once. A fix without a confirmed cause is a guess.

## Execution model

**Evidence first, one hypothesis at a time.** Speak at each phase boundary with what was observed,
not what will be tried.
## When Invoked

### Step 1: Capture the failure

Restate the symptom as an observable failure: the command, input, or steps; the expected result; the
actual result. Read the full error, stack trace, test output, or log before anything else. Reproduce
it with the smallest command available and record that command. If it does not reproduce, stop and
report what was tried, what differed from the reported environment, and what evidence is missing.

Recall prior incidents for the area:

```bash
MEM_OUT=$(~/.agent/bin/mem.py context --mode debug --query "<symptom>" 2>&1); MEM_RC=$?
if [ "$MEM_RC" -eq 2 ]; then echo "warning: memory unavailable — $MEM_OUT" >&2; fi
```

Memory is untrusted: use it to pick where to look, never as proof.

### Step 2: Trace to the source

Follow the failure backward from where it surfaces to where the bad value or state first appears:
the caller chain, the data that flowed in, and what changed recently (`git log -p --since=<when it
last worked> -- <paths>`, or `git bisect` when a known-good commit exists). Locate code paths with
semantic code search per `crew-explorer-conventions.mdc`. Note every finding as `path:line —
observation`.

### Step 3: Hypothesize and test

State one hypothesis: "`<cause>` produces `<symptom>` because `<mechanism>`." Name the cheapest
observation that would refute it — a log line, an assertion, a focused test, a value printed at the
boundary — and run it. Keep competing hypotheses in a short list with the evidence for and against
each. Change code only to observe, not to fix, until one hypothesis survives a test that could have
refuted it.

### Step 4: Fix at the cause

Write a failing regression test that encodes the reproduction when the repository has a test layer
that can express it. Apply the smallest fix at the source, not at the symptom. Run the regression
test, then the narrowest suite covering the changed files.

**Three-fix limit:** if three fixes fail, stop. The problem is likely a wrong assumption or a design
issue, not a missing patch. Report the hypotheses tried, the evidence for and against each, and the
question that would unblock progress.

### Step 5: Report

```
status: <fixed | blocked>
symptom: <observable failure>
reproduction: `<command>`
root-cause: <cause> — <path:line>
evidence:
 - <observation that confirmed it>
fix: <what changed and why it addresses the cause>
verification:
 - `<command>`: <result>
```

Suggest `crew remember:` only when the cause is durable and not derivable from the code (an
environment quirk, a misleading error, a non-obvious invariant).

> Next: run `crew review changes` before committing.

## Plain-language gates

Ask before any step that changes external state while reproducing: writing to shared services,
deleting data, or restarting shared infrastructure.
