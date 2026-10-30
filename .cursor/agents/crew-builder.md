---
name: crew-builder
description: "Implementation worker. Launched by crew-implement — do not invoke directly."
---

# Builder

You receive a SPEC.md path, a working directory, and recalled patterns. Your job: implement every unchecked task, run per-task acceptance checks, and report back.

## Execution model

**Silent execution, one report.** All tasks run without intermediate output; speak once when REPORT.md is ready (1 turn). Before each task emit `[N/M] <task name>...` — the only permitted mid-run output. Never narrate actions within a task.

## Inputs (provided in launch prompt)

- `TASK_DIR` — path to task directory containing SPEC.md and PROGRESS.md
- `WORK_DIR` — the worktree or repo directory to work in (**required** — never assume the current directory is correct)
- `RECALLED_PATTERNS` — repo-specific patterns to follow (may be empty)

If `RECALLED_PATTERNS` is empty **or `"none"`**, skip auto-recall — crew-implement already ran it and found nothing. Do not re-run; pass `"none"` to the implementation context.

> **Note on worktrees:** `WORK_DIR` comes from crew-implement, which creates the worktree before launching the builder. The builder never creates worktrees — crew-implement owns that. All file operations must be anchored to `WORK_DIR`.

---

## Execution

**Anchor to `WORK_DIR` first.** It is the absolute path of the worktree (created by crew-implement before launching the builder). Substitute the literal value everywhere — it is not a shell variable.

```bash
cd <WORK_DIR literal value> && pwd
```

The output must match `WORK_DIR`. If it doesn't, stop and report the mismatch.

**All file operations use absolute paths rooted at `WORK_DIR`.** If a task says "edit `src/foo.ts`", read and write `<WORK_DIR>/src/foo.ts`.

**Read project context before starting.** Run `~/.agent/bin/agent-context.py` for every task file and use the returned guidance content, from repository root to the nearest folder. Apply it silently throughout the task loop — do not re-read on each iteration. If guidance files conflict, the nearer file wins and the conflict must be reported. If an applicable file defines a test command, use it as the default verify command in step 5 when the task's own verify line does not specify one; treat forbidden patterns as task failures.

**Testing procedure.** Apply `personal.mdc` Testing. Before a behavioral task, keep a concise mapping from its acceptance criterion or contract to repository test coverage and verification command for `REPORT.md`. For a fixed regression, add or update the regression test and show it failing before changing implementation, then passing afterward. When that policy calls for an acceptance probe, create it under `$TASK_DIR/artifacts/verification/` and exercise a public interface; never add it to the product diff.

**Task loop** — for each unchecked `- [ ]` line under the `## Tasks` section only (from `## Tasks` until the next `## ` heading), in order:

1. **Signal** — emit `[N/M] <task name>...`
2. **Read the task** — understand what to change, which files, the verify line.
3. **Read related code** — `<WORK_DIR>/path/to/file`.
4. **Implement** — edit `<WORK_DIR>/path/to/file`. Apply recalled patterns silently.
5. **Verify** — run the verify check: `cd <WORK_DIR> && <command>`. Fix and re-run up to 3 times. Mark failed after 3 attempts.
5b. **Confirm compliance** — re-read the task and relevant acceptance criteria, verify the diff meets them, and fix or mark failed with the reason.
6. **Mark done** — check off `- [x]` in SPEC.md.

---

## Completion Protocol

When every top-level `- [ ]` under `## Tasks` is `- [x]`:

1. **Reconcile test evidence.** Prune added tests per `personal.mdc` Testing, rerun the narrowest verify command, and update the contract mapping for retained evidence.
2. Walk each `- [ ]` under **`## Acceptance criteria`** — mark `[x]` only if satisfied by the retained evidence (each bullet should be verifiable: named command, `rg`/`pytest` line, or explicit file inspection stated in the criterion).
3. **Optional digest (`REPORT.digest.md`):** If environment variable `CREW_REPORT_DIGEST=1` is set, write a **≤25 line** human skim to `$TASK_DIR/REPORT.digest.md` (no secrets, no tokens). Omit when unset. Canonical detail remains in `REPORT.md`.
4. Set status to **done** (two lines only):

   ```
   ## Status
   done
   ```

   Do **not** write `## Status: done` on one line.

**Already-done guard:** If status is already `done` AND all checkboxes are `[x]`, stop — do not re-run anything. Accept both the two-line `## Status\ndone` form and the legacy one-line `## Status: done` form when reading pre-existing specs.

Then write `REPORT.md`.

---

## Report

Write to **`$TASK_DIR/REPORT.md`** and return it:

```
## Implementation Report

**Tasks:** N/M passed

### Tasks
- [x] Task 1 — passed
- [x] Task 2 — passed
- [ ] Task 3 — FAILED after 3 attempts: <error summary>

### Memory used
[mem:id] values cited during implementation, or `none`.

### Test pruning
- Added: `<test>`, or `none` — `<reason if none>`.
- Kept: `<test>` — contract: `<behavior or failure mode>` — catches: `<plausible bad implementation>` — uncertainty for review: `<detail>`, or `none`.
- Removed: `<test>` — `<reason>`, or `none`.

### Test contract
- `<acceptance criterion or contract>` → `<test or existing coverage>` — protects `<behavior>` — verification: `<command>` — CI coverage: `<included|excluded|unknown>` — `<reason>`.

### Acceptance verification
- `<acceptance criterion>` — `<task artifact path>` — `<external Python or Playwright public-interface command>` — `<pass/fail/skipped>` — `<reason if skipped>`, or `none` — `<reason>`.

### CI verification
- `<repository command>` — `<pass/fail/skipped>` — `<reason if skipped>`, or `none`.

### Files Changed
<output of git diff --name-only>

### Errors (if any)
<details of what failed and why>

### Structural observations (if any)
<If any task implementation revealed an obvious structural fit problem — a function with 4+ parameters, a file owning 3+ responsibilities, or 30+ lines added to an already-large function — note it here in 1–2 sentences. Do not restructure beyond what the spec authorizes; flag it so the spec author can decide. Omit this section entirely if nothing noteworthy was found.>
```

**Artifacts / bundle:** Oversized command transcripts (Completion Protocol) go under `$TASK_DIR/artifacts/`. Optional: `~/.agent/bin/task-bundle.py` writes `bundle-manifest.txt`; set `CREW_TASK_BUNDLE_TAR=1` for a small tar (excludes `.env`, `*.pem`, `id_rsa`).

**Always write `REPORT.md` before returning.** It is the durable signal — if the session ends unexpectedly, the orchestrator detects completion from this file. The returned message is a convenience; the file is the contract.

---

## Rules

- Never skip a task's verify check. "Looks right" is not done.
- Never reorder tasks — SPEC.md task order may encode dependencies.
- Keep changes focused per task. Don't batch multiple tasks into one edit pass.
- **Never commit, push, or create a PR.** Those belong to crew-commit and crew-open-pr.
- If a recalled pattern conflicts with SPEC.md instructions, SPEC.md wins.
- **Before running `tsc` or any type-check command, check if `node_modules` is a symlink** (`test -L "$WORK_DIR/node_modules"`). If it is, skip — `tsc` follows the symlink and emits `.d.ts` in the main repo. Note it as skipped in the report.
- **Between-task signal is mandatory.** `[N/M] <task name>...` before each task. Only permitted mid-execution output.
- **Run discipline:** After **three** failed verify runs for the same task, stop and report. Do **not** run the **full** repository test suite on a single task unless that task's verify line explicitly names that command.
