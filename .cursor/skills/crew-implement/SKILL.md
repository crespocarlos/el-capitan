---
disable-model-invocation: true
name: crew-implement
description: "Orchestrate implementation of an approved SPEC.md. Trigger: 'crew implement'."
---

**Workflow**: build | **Stage**: implement

# crew-implement

Orchestrate implementation of an approved SPEC.md. Handles setup, gates, and user interaction — then
launches the implementation worker for the heavy lifting.

## Workflow

### Step 1: Resolve task state

First, check if the user's message contains a file path ending in `SPEC.md` or `spec.md` (e.g. `here
is the spec /some/path/to/spec.md`). If found, attempt to read that file. If the read fails (file
not found), stop immediately: 'Cannot read [path] — check the path and try again.' If the file
exists but has no `## Status` section or the status value (compared case-insensitively) is neither
`approved` nor `IMPLEMENTING`, stop: 'Spec status is [value]; expected `approved` or
`IMPLEMENTING`.' (For an `ON-HOLD (… was <status>)` value, add: 'Set Status back to the `was` value
to resume.') Otherwise, set `TASK_DIR` to its parent directory, export
`CREW_TASK_DIR="$TASK_DIR"`, and skip to Step 2.

Otherwise:

```bash
source ~/.agent/bin/task-env.sh
~/.agent/bin/crew-task-context.py --artifacts task_id,spec,progress,report,handoff --max-chars 4000
```

If `$TASK_DIR` is non-empty, use the returned available artifacts to resume; do not assume a spec,
progress log, report, or handoff exists. If empty, scan globally for other specs (see Step 2).

**If `CREW_TASK_STATE=error`, stop here** — before the scan above — and report the resolver message:
the repo state is unreadable (detached HEAD, no `origin` remote), so task state cannot be determined
and every gate below would silently skip. A scan is only valid for `CREW_TASK_STATE=none`.

### Step 2: Gate check

If no task was resolved (TASK_DIR is empty), scan globally for other specs (most recent first):

```bash
find ~/.agent/tasks -name "SPEC.md" -type f -exec stat -f "%m %N" {} \; 2>/dev/null | sort -rn | awk '{print $2}'
```

For each found SPEC.md, read its first line (title) and `## Status` field to build a list.

- If specs exist (under the current branch or elsewhere), present non-DONE specs sorted by last
  modified (newest first) as a table of #, repo/branch/task, title, status, and last modified:

> "Found these specs: [table] — Which one? (or run `crew spec` to draft a new one)"

When the user picks one, set `TASK_DIR` to that spec's parent directory and continue.

- If no specs exist anywhere, stop: > "No specs found. Run `crew spec` first to draft one."

If the SPEC.md status is `DRAFTING`, stop:

> "The spec hasn't been approved yet. Get approval before implementing."

If the status is already `IMPLEMENTING` and PROGRESS.md has completed tasks, you're resuming —
inform the user which tasks are done and which remain.

### Step 3: Prepare

From the checkout the spec was drafted in, one call does the setup:

```bash
~/.agent/bin/crew-task.py prepare-implement "$TASK_DIR" [--where worktree|here] [--branch <name>]
```

In order it settles where the worker runs, cuts or keeps the branch (default: the spec's `## Branch:`)
or creates the worktree, runs `mark-implementing --branch --root`, logs `implement_start` and
`stage_start`, writes `BASELINE.diff` once (`crew commit` reads it for out-of-scope edits), recalls
memory, and writes the builder prompts under `$TASK_DIR/dispatch/`; it writes no lock. Line one is
`WORK_DIR`; line two names the branch and the prompt files. On failure it names its step on stderr:
exit 1 is a decision for the user (the worktree question, a dirty tree, a `--branch` other than the
checked-out one, an unreadable atomic line, an unapproved spec): ask it the way [worker
dispatch](references/worker-dispatch.md) says, then run again. Exit 2 is a failed step: report it and
stop. No worker is dispatched for a task whose branch was not recorded.

### Step 4: Bootstrap dependencies

Read the repo's `AGENTS.md` (or `CONTRIBUTING.md`) for a setup command and run it in `WORK_DIR`. The
UUID task directory (`$TASK_DIR`) is stable and does not move.

### Step 5: Launch worker

Write the worker lock right before the first dispatch, never before Step 4's bootstrap:
`~/.agent/bin/crew-task.py lock write "$WORK_DIR" --task "$(basename "$TASK_DIR")"`. Launch crew-builder as a background subagent in Cursor (`run_in_background: true`; Claude Code:
read `~/.cursor/agents/crew-builder.md` or `~/.claude/agents/crew-builder.md` and follow its protocol
directly), per [dispatch reliability](references/worker-dispatch.md#dispatch-reliability). The prompt
is a `$TASK_DIR/dispatch/builder*.md` file, unchanged: `crew-task:` and `TASK_RANGE` lines,
`TASK_DIR`, the literal `WORK_DIR`, `RECALLED_PATTERNS` and the open tasks. The worker reads
crew-builder itself, so never paste rules into the prompt. Several files are batches, dispatched in
order: [worker dispatch](references/worker-dispatch.md), "Batching for large specs", which also holds
the blocked line, cost line and message routing.

### Step 6: Handle results

Read the worker's report first: the file is the contract and everything below is read from it. The
worker's final reply is the report itself, from `## Implementation Report` on; a worker cannot write
the file, so the reply is saved as `REPORT.md` (a batch: `REPORT.part-<first>-<last>.md`; the final
batch: both). The subagent-stop hook saves it, in Claude Code and Cursor. Only when that file is
missing after the worker stops is the save yours: pipe the reply, unchanged, into
`~/.agent/bin/crew-task.py report save "$TASK_DIR"` (a batch adds `--range <first>-<last>`, the
final batch also `--final`). A report that fails `report-check` is still saved, with a WARN line
in PROGRESS.md: read it before trusting the gate results. If neither the file nor a reply with that
heading exists, tell the user:

> "The worker finished but didn't produce a report. Check `$TASK_DIR/` for SPEC.md task status, or
> re-run `crew implement` to resume."

When the Implementation Report is available:

**All tasks passed:**

0. Re-run the gates as CI does (a pass on an unchanged tree is reused): `~/.agent/bin/crew-verify.py --repo
   <WORK_DIR> --task-dir "$TASK_DIR"`; act on its outcome per [verify outcomes](references/verify-outcomes.md).
1. Run the completion metric:

   ```bash
   ~/.agent/bin/crew-metric.py "$TASK_DIR" implement_complete result=ok 2>/dev/null || true
   ```
2. **Draft memory candidates** per [completion handoff](references/completion-handoff.md): zero to
   three typed drafts in `~/.agent/memory/.inbox/`, written without asking. Nothing is stored or
   imported here; `crew open pr` asks the one closing question.
3. **Tell the user**, because the next stages need the tree and the status:
   > "All tasks done. Status stays `IMPLEMENTING` until the PR is opened."
   > "Working directory: `<WORK_DIR>` — run tests from there."

   The handoff itself is the trailer at the end of this file; do not repeat it here.

**Some tasks failed:**

1. Show the user which tasks failed and the error summaries from the report.
2. Ask: "Want to retry the failed tasks, skip them, or stop here?"
   - **Retry** → re-launch the worker with only the failed tasks
   - **Skip** → proceed to diff-check with partial implementation
   - **Stop** → leave PROGRESS.md as IMPLEMENTING for later resumption

## Rules

- Never start the worker without an approved SPEC.md.
- The skill handles every user interaction; the worker is non-interactive.
- Surface worker failures to the user with options.
- Tests the run adds follow the [testing policy](~/.cursor/agents/references/testing-policy.md).
- **Stop after all tasks pass.** Never commit, push, or create a PR; output the Step 6 handoff
  before stopping. Committing and opening the PR belong to `crew-task.py ship`, which `crew open pr`
  runs after the owner approves the PR.
- **Code changes follow crew-builder's protocol**, through the subagent or by reading and following
  the protocol directly, never ad hoc. The orchestrator handles setup and verification.

## Plain-language gates

Use plain language, without compressed summaries, at each gate checkpoint:

- Before presenting the SPEC.md for approval (Gate 1) — summarize what will be built and list acceptance criteria in plain language
- Before surfacing worker failures — state what failed and what the user's options are plainly; do not compress error messages or file paths
- When a task's verify command fails three times — report the failure in full detail without compression (three-failure stop rule)

Continue once the user provides direction.

> Next: run `crew review` to verify the change, then `crew open pr`, which ships it with `crew-task.py ship`.
