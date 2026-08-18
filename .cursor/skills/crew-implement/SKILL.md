---
name: crew-implement
description: "Orchestrate implementation of an approved SPEC.md. Trigger: 'crew implement'."
---

**Workflow**: build | **Stage**: implement

# crew-implement

Orchestrate implementation of an approved SPEC.md. Handles setup, gates, and user interaction — then launches the implementation worker for the heavy lifting.

## Workflow

### Step 1: Resolve task state

First, check if the user's message contains a file path ending in `SPEC.md` or `spec.md` (e.g. `here is the spec /some/path/to/spec.md`). If found, attempt to read that file. If the read fails (file not found), stop immediately: 'Cannot read [path] — check the path and try again.' If the file exists but has no `## Status` section or the status value is not `approved`, stop: 'Spec status is [value] — get approval before implementing.' Otherwise, set `TASK_DIR` to its parent directory, export `CREW_TASK_DIR="$TASK_DIR"`, and skip to Step 2.

Otherwise:

```bash
if [ -n "${CREW_TASK_DIR+x}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
elif TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null); then
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
  > | #   | Repo / Branch / Task                             | Title                        | Status       | Last modified |
  > | --- | ------------------------------------------------ | ---------------------------- | ------------ | ------------- |
  > | 1   | kibana / main / add-retry-logic                  | Retry logic for async search | APPROVED     | 2 hours ago   |
  > | 2   | kibana / feature/error-handling / improve-errors | Improve error boundaries     | IMPLEMENTING | 3 days ago    |
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
RECALLED_PATTERNS=$(~/.agent/bin/journal-search.py auto-recall "$REPO" --top 10 2>/dev/null || true)
```

Store as `RECALLED_PATTERNS` to pass to the subagent. If the output is empty (no journal entries or search unavailable), set `RECALLED_PATTERNS="none"` — do **not** leave it as an empty string. Passing an empty string causes crew-builder to re-run auto-recall redundantly.

### Step 4: Branch setup

**If already on a feature branch** (not `main` or the default branch): set `WORK_DIR` to the current directory and proceed to Step 5.

**If on the default branch:** ask the user:

> "Create a worktree for this implementation, or work directly on this branch? (worktree / here)"

  Read the branch name from SPEC.md:
  ```bash
  BRANCH_NAME=$(grep "^## Branch:" "$TASK_DIR/SPEC.md" | sed 's/^## Branch: *//')
  ```
  If `## Branch:` is absent or empty, derive it from the SPEC.md type and goal (type-prefix/slug, ≤50 chars), propose it, and confirm before proceeding.

  - **worktree** — fetch the default branch and create a worktree:

  ```bash
  DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $NF}')
  git fetch origin "$DEFAULT_BRANCH"
  cd "$(~/.agent/bin/manage-worktree.sh -b "$BRANCH_NAME" "origin/$DEFAULT_BRANCH")"
  ```

  After the worktree is created: **bootstrap dependencies.** Read the repo's `AGENTS.md` (or `CONTRIBUTING.md`) for a setup/bootstrap command and run it in the worktree. Set `WORK_DIR` to the worktree directory.

- **here** — set `WORK_DIR` to the current directory. Ask:

  > "Create a new branch (`$BRANCH_NAME`), or commit directly to `<current-branch>`? (new-branch / here)"

  - **new-branch** — create and checkout the branch:

    ```bash
    DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $NF}')
    git fetch origin "$DEFAULT_BRANCH"
    git checkout -b "$BRANCH_NAME" "origin/$DEFAULT_BRANCH"
    ```

  - **here** — work in the current directory on the current branch as-is.

The UUID task directory (`$TASK_DIR`) is stable — it does not move either way.

### Step 5: Update progress

```bash
~/.agent/bin/log-progress.py "$TASK_DIR" "APPROVED → IMPLEMENTING"
~/.agent/bin/log-metric.py "$TASK_DIR" implement_start 2>/dev/null || true
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

Launch crew-builder as a background subagent in Cursor (`run_in_background: true`; Claude Code: follow crew-builder's protocol directly). This avoids terminating a healthy implementation run at the synchronous turn limit. Pass these inputs:

- `TASK_DIR` — the resolved task directory path (absolute)
- `WORK_DIR` — the worktree or repo directory (absolute path, e.g. `/Users/you/repo-feature/feature-xyz`). This is the directory where ALL file reads, edits, and shell commands must run. It is not a shell variable — pass the literal path.
- `RECALLED_PATTERNS` — the patterns found in Step 3 (or "none")
- The full contents of `SPEC.md` (so the worker has it without needing to re-read)

### Step 7: Handle results

Read `$TASK_DIR/REPORT.md`. If the worker returned a message, use that. If neither exists, tell the user:

> "The worker finished but didn't produce a report. Check `$TASK_DIR/` for SPEC.md task status, or re-run `crew implement` to resume."

When the Implementation Report is available:

**All tasks passed:**

1. ```bash
   ~/.agent/bin/log-metric.py "$TASK_DIR" implement_complete result=ok 2>/dev/null || true
   ~/.agent/bin/log-progress.py "$TASK_DIR" "IMPLEMENTING → REVIEW"
   ( export TASK_DIR="$TASK_DIR"; ~/.agent/bin/task-bundle.py ) || true
   ```
2. Append to `$TASK_DIR/SESSION.md`:
   ```
   [TIME] crew-implement: completed N/N tasks, files: <changed files from report>
   ```
3. **Auto-journal** — append a journal entry (no prompt, passive):
   ```bash
   JOURNAL_FILE=~/.agent/journal/$(date +%Y-%m).md
   mkdir -p ~/.agent/journal
   ```
   Write a prose entry following `~/.agent/_JOURNAL_TEMPLATE.md` format. Use `$(date +%Y-%m-%d)` for the date. Title prefix: "Implemented:". Write 1-3 paragraphs in plain prose — each paragraph one self-contained idea. Derive from SPEC.md + REPORT.md:
   - What was built and why it matters (always)
   - What broke or surprised during implementation, if REPORT.md has structural observations (omit if nothing notable)
   - Patterns or constraints discovered worth remembering (omit if nothing new)

   Append with:
   ```bash
   ~/.agent/bin/journal-search.py add "$JOURNAL_FILE" --entry "$(date +%Y-%m-%d)" 2>/dev/null \
     && echo "[journal] Journaled to $JOURNAL_FILE" \
     || echo "[journal] Warning: index failed — entry written but not searchable"
   ```

4. **Tell the user — this output is mandatory, do not skip it:**
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
- **Stop after all tasks pass.** Never commit, push, or create a PR. Always output the handoff message (Step 7) before stopping.
- **ALWAYS follow crew-builder's protocol for implementation.** The orchestrator handles setup and gates. Code changes follow crew-builder's instructions — either via a subagent (Cursor Task tool) or by reading and following crew-builder's protocol directly. Never skip crew-builder's protocol and implement ad-hoc.

## Auto-clarity override

Drop to plain language at each gate checkpoint:

- Before presenting the SPEC.md for approval (Gate 1) — summarize what will be built and list acceptance criteria in plain language
- Before surfacing worker failures — state what failed and what the user's options are plainly; do not compress error messages or file paths
- When a task's verify command fails three times — report the failure in full detail without compression (three-failure stop rule)

Resume compressed mode once the user provides direction.
