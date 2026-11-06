---
disable-model-invocation: true
name: crew-quick
description: "Implement a small change without a spec: ≤3 files, no new exports or API surface. Trigger: 'crew quick <description>'."
---

**Workflow**: lightweight | **Stage**: implement → review

# Quick Change

The lightweight path from `crew-orchestrator.mdc`: implement inline, review staged changes, hand off
to commit. No spec, worktree, or task state.

## When Invoked

### Step 1: Size gate

From the request and a targeted search, list the files the change will touch and whether it adds or
changes an exported symbol, route, schema, configuration key, or other public contract. If it
touches more than 3 files or changes any public contract, stop:

> "This exceeds the quick path (<reason>). Run `crew spec` to plan it."

State the acceptance check in one line — the command or inspection that proves the change works.
Confirm it with the user only when the request leaves it ambiguous.

### Step 2: Implement

Run `~/.agent/bin/agent-context.py <files>` and apply the returned guidance. Make the change under
`crew-builder.md` rules for testing, verification, and scope: add a regression test first for a bug
fix, keep the diff to the stated files, and never commit. Run the acceptance check and the
repository's lint and type-check for the changed files. Fix and re-run up to three times; then stop
and report.

### Step 3: Review

Stage only the changed files with `git add <files>` and run the `crew review changes` protocol from
`~/.cursor/agents/crew-reviewer.md` inline. With no `TASK_DIR`, persist the review under
`/tmp/crew-review-<repo>/review/<timestamp>` (the reviewer's documented fallback) and skip
`crew log`. A `BLOCK` verdict stops the handoff; `crew commit` is only offered on `PASS` or `WARN`.

### Step 4: Hand off

```
status: <ready | blocked>
changed:
 - <path>: <change>
checks:
 - `<command>`: <result>
review: <PASS | WARN | BLOCK>
```

> Next: run `crew commit` to continue, or `crew review address` if the review blocked.
