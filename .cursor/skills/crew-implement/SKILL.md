# crew-implement

Orchestrate implementation of an approved SPEC.md. Handles setup, gates, and user interaction — then launches the implementation worker subagent for the heavy lifting.

## Workflow

### Step 1: Resolve task state

```bash
REPO=$(basename $(git rev-parse --show-toplevel))
BRANCH=$(git branch --show-current)
BRANCH_DIR=~/.agent/tasks/$REPO/$BRANCH
```

Scan for specs under the current branch (each task lives in its own slug subdirectory):

```bash
find "$BRANCH_DIR" -maxdepth 2 -name "SPEC.md" -type f 2>/dev/null
```

Filter to non-DONE specs (where `## Status` is not `done`). If exactly one, set `TASK_DIR` to its parent directory and read `SPEC.md` + `PROGRESS.md`. If multiple non-DONE specs exist, present a choice (see Step 2).

Backward compat: if no subdirectory specs are found but `$BRANCH_DIR/SPEC.md` exists (old flat layout), use `BRANCH_DIR` as `TASK_DIR`.

### Step 2: Gate check

If no specs were found under `$BRANCH_DIR`, scan globally for other specs (most recent first):

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
~/.agent/tools/journal-search.py auto-recall "$REPO" --top 5 2>/dev/null || true
```

Store the results as `RECALLED_PATTERNS` to pass to the subagent.

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

1. Determine the slug (basename of the current `TASK_DIR`). Move the entire slug directory to the new branch:
   ```bash
   SLUG=$(basename "$TASK_DIR")
   NEW_BRANCH_DIR=~/.agent/tasks/$REPO/$BRANCH_NAME
   mkdir -p "$NEW_BRANCH_DIR"
   mv "$TASK_DIR" "$NEW_BRANCH_DIR/$SLUG"
   TASK_DIR="$NEW_BRANCH_DIR/$SLUG"
   ```
2. Set `WORK_DIR` to the worktree directory.

If skipped (already on feature branch), set `WORK_DIR` to the current directory.

### Step 5: Update progress

Set PROGRESS.md to:
```
## Status: IMPLEMENTING
## Current: implement
## Next: diff-check
```

### Step 6: Detect mode and launch worker

```bash
which ralph 2>/dev/null || which ralph.sh 2>/dev/null
```

If found and the user didn't say "implement inline", set `MODE=ralph`. Otherwise `MODE=inline`.

**Read the `@crew-builder` agent now.** It contains the full protocol for both ralph and inline modes. Launch the `@crew-builder` subagent following that protocol, passing:
- `TASK_DIR` — the resolved task directory path (absolute)
- `WORK_DIR` — the worktree or repo directory (absolute path, e.g. `/Users/you/repo-feature/feature-xyz`). This is the directory where ALL file reads, edits, and shell commands must run. It is not a shell variable — pass the literal path.
- `RECALLED_PATTERNS` — the patterns found in Step 3 (or "none")
- `MODE` — `ralph` or `inline`
- The full contents of `SPEC.md` (so the subagent has it without needing to re-read)

Do NOT skip ralph when `MODE=ralph`. If ralph is detected, the subagent MUST use it — falling back to inline implementation is not acceptable unless ralph fails to start.

### Step 7: Handle results

Read `$TASK_DIR/REPORT.md`. If the subagent returned a message, use that. If the subagent exited without returning (ralph mode, session timeout), fall back to `REPORT.md`. If neither exists, tell the user:

> "The worker finished but didn't produce a report. Check `$TASK_DIR/` for SPEC.md task status, or re-run `crew implement` to resume."

When the Implementation Report is available:

**All tasks passed:**
1. Update PROGRESS.md:
   ```
   ## Status: DIFF_CHECK
   ## Current: diff-check
   ## Next: commit
   ```
2. Append to `$TASK_DIR/SESSION.md`:
   ```
   [TIME] crew-implement: completed N/N tasks, files: <changed files from report>
   ```
3. Tell the user:
   > "All tasks done. Ready for `crew diff`."

**Some tasks failed:**
1. Show the user which tasks failed and the error summaries from the report.
2. Ask: "Want to retry the failed tasks, skip them, or stop here?"
   - **Retry** → re-launch the subagent with only the failed tasks
   - **Skip** → proceed to diff-check with partial implementation
   - **Stop** → leave PROGRESS.md as IMPLEMENTING for later resumption

## Rules

- Never start the subagent without a gate-checked, approved SPEC.md
- Always create the worktree before launching the subagent
- The skill handles ALL user interaction — the subagent is non-interactive
- If the subagent returns failures, always surface them to the user with options
- **Stop after all tasks pass.** Never commit, push, or create a PR.
