**Workflow**: build | **Stage**: implement

# crew-implement

Orchestrate implementation of an approved SPEC.md. Handles setup, gates, and user interaction — then launches the implementation worker for the heavy lifting.

## Workflow

### Step 1: Resolve task state

```bash
if [ -n "${CREW_TASK_DIR+x}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
elif TASK_DIR=$(~/.agent/tools/resolve-task-dir.py 2>/dev/null); then
  export CREW_TASK_DIR="$TASK_DIR"
else
  echo "Warning: resolve-task-dir failed — check git remote and branch." >&2
  TASK_DIR=""
fi
```

If `$TASK_DIR` is non-empty, read `SPEC.md` + `PROGRESS.md`. If empty, scan globally for other specs (see Step 2).

### Step 2: Gate check

If no task was resolved (TASK_DIR is empty), scan globally for other specs (most recent first):

```bash
find ~/.agent/tasks -name "SPEC.md" -type f -exec stat -f "%m %N" {} \; 2>/dev/null | sort -rn | awk '{print $2}'
```

For each found SPEC.md, read its first line (title) and `## Status` field to build a list.

- If specs exist (under the current branch or elsewhere), present non-DONE specs sorted by last modified (newest first):
  > "Found these specs:"
  >
  > | # | Repo / Branch / Task | Title | Status | Last modified |
  > |---|---|---|---|---|
  > | 1 | kibana / main / add-retry-logic | Retry logic for async search | APPROVED | 2 hours ago |
  > | 2 | kibana / feature/error-handling / improve-errors | Improve error boundaries | IMPLEMENTING | 3 days ago |
  >
  > "Which one? (or run `crew spec` to draft a new one)"

  When the user picks one, set `TASK_DIR` to that spec's parent directory and continue.

- If no specs exist anywhere, stop:
  > "No specs found. Run `crew spec` first to draft one."

If the SPEC.md status is `DRAFTING`, stop:
> "The spec hasn't been approved yet. Get approval before implementing."

If the status is already `IMPLEMENTING` and PROGRESS.md has completed tasks, you're resuming — inform the user which tasks are done and which remain.

### Step 3: Auto-recall

```bash
REPO=$(basename $(git rev-parse --show-toplevel))
RECALLED_PATTERNS=$(~/.agent/tools/journal-search.py auto-recall "$REPO" --top 5 2>/dev/null || true)
```

Store as `RECALLED_PATTERNS` to pass to the subagent. If the output is empty (no journal entries or search unavailable), set `RECALLED_PATTERNS="none"` — do **not** leave it as an empty string. Passing an empty string causes crew-builder to re-run auto-recall redundantly.

### Step 4: Create worktree

If already on a feature branch (not `main` or the default branch), skip this step.

Otherwise, fetch the latest from the default branch and create a worktree:

```bash
DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $NF}')
git fetch origin "$DEFAULT_BRANCH"

BRANCH_NAME=<type>/<short-description>
cd "$(~/.agent/tools/manage-worktree.sh -b "$BRANCH_NAME" "origin/$DEFAULT_BRANCH")"
```

Use a conventional branch prefix based on the SPEC.md type:

| SPEC type | Prefix |
|-----------|--------|
| Feature / enhancement | `feature/` |
| Bug fix | `bugfix/` |
| Refactor | `refactor/` |
| Chore / tooling | `chore/` |
| Docs | `docs/` |

Read the `## Type` field from SPEC.md to pick the prefix. Derive the short description from the issue title or SPEC.md goal (lowercase, hyphen-separated).

After the worktree is created:

1. **Bootstrap dependencies.** Read the repo's `AGENTS.md` (or `CONTRIBUTING.md`) for a setup/bootstrap command and run it in the worktree. This ensures the worktree has its own `node_modules` instead of symlinks to the main repo.

2. Set `WORK_DIR` to the worktree directory (the script outputs the resolved absolute path).

The UUID task directory (`$TASK_DIR`) is stable — it does not move when a worktree is created.

If skipped (already on feature branch), set `WORK_DIR` to the current directory.

### Step 5: Update progress

```bash
~/.agent/tools/log-progress.py "$TASK_DIR" "APPROVED → IMPLEMENTING"
```

### Step 5b: Capture baseline diff

Before making any code changes, capture the current state of the working tree:

```bash
# Re-entry guard: skip if BASELINE.diff already exists (resuming a previous session)
if [ ! -f "$TASK_DIR/BASELINE.diff" ]; then
  git diff HEAD > "$TASK_DIR/BASELINE.diff"
fi
```

This snapshot is used by `crew commit` to detect out-of-scope modifications.

### Step 6: Launch worker

**Read the crew-builder agent now** — find it at `~/.cursor/agents/crew-builder.md` or `~/.claude/agents/crew-builder.md` (whichever exists).

#### Step 6a — Ralph check (required, do not skip)

```bash
which ralph 2>/dev/null || which ralph.sh 2>/dev/null
```

This check is mandatory. Do not proceed to 6b or 6c without running it.

#### Step 6b — Ralph mode (if ralph found)

Launch crew-builder as a subagent (Cursor: Task tool; Claude Code: `ralph run` directly). Pass `MODE=ralph`. Ralph manages its own iterations — crew-builder waits for it to exit.

#### Step 6c — Inline mode (only if ralph not found)

Launch crew-builder as a subagent if possible (Cursor: Task tool). If subagents are not available (Claude Code), follow crew-builder's inline protocol directly. Pass `MODE=inline`.

When ralph is unavailable, crew-builder's protocol is executed inline. Claude handles the build steps directly in the current session — reads each task from SPEC.md, implements it, runs the acceptance check, and marks it done. The same tasks and checks run; the difference is conversational (inline) rather than autonomous (ralph).

Pass these inputs to crew-builder (or use them when following its protocol):
- `TASK_DIR` — the resolved task directory path (absolute)
- `WORK_DIR` — the worktree or repo directory (absolute path, e.g. `/Users/you/repo-feature/feature-xyz`). This is the directory where ALL file reads, edits, and shell commands must run. It is not a shell variable — pass the literal path.
- `RECALLED_PATTERNS` — the patterns found in Step 3 (or "none")
- `MODE` — `ralph` or `inline`
- The full contents of `SPEC.md` (so the worker has it without needing to re-read)

### Step 7: Handle results

Read `$TASK_DIR/REPORT.md`. If the worker returned a message, use that. If the worker exited without returning (ralph mode, session timeout), fall back to `REPORT.md`. If neither exists, tell the user:

> "The worker finished but didn't produce a report. Check `$TASK_DIR/` for SPEC.md task status, or re-run `crew implement` to resume."

When the Implementation Report is available:

**All tasks passed:**
1. ```bash
   ~/.agent/tools/log-progress.py "$TASK_DIR" "IMPLEMENTING → REVIEW"
   ```
2. Append to `$TASK_DIR/SESSION.md`:
   ```
   [TIME] crew-implement: completed N/N tasks, files: <changed files from report>
   ```
3. Tell the user:
   > "All tasks done. Ready for `crew review`."
   > "Working directory: `<WORK_DIR>` — run tests from there."

> Next: run `crew review` to continue.

**Some tasks failed:**
1. Show the user which tasks failed and the error summaries from the report.
2. Ask: "Want to retry the failed tasks, skip them, or stop here?"
   - **Retry** → re-launch the worker with only the failed tasks
   - **Skip** → proceed to diff-check with partial implementation
   - **Stop** → leave PROGRESS.md as IMPLEMENTING for later resumption

## Rules

- Never start the worker without a gate-checked, approved SPEC.md
- Always create the worktree before launching the worker
- The skill handles ALL user interaction — the worker is non-interactive
- If the worker returns failures, always surface them to the user with options
- **Stop after all tasks pass.** Never commit, push, or create a PR.
- **ALWAYS follow crew-builder's protocol for implementation.** The orchestrator handles setup and gates. Code changes follow crew-builder's instructions — either via a subagent (Cursor Task tool), ralph, or by reading and following crew-builder's inline protocol directly. Never skip crew-builder's protocol and implement ad-hoc.
