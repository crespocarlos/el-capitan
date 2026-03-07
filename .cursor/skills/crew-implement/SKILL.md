# crew-implement

Orchestrate implementation of an approved SPEC.md. Handles setup, gates, and user interaction — then launches the implementation worker subagent for the heavy lifting.

## Workflow

### Step 1 — Resolve task state

```bash
REPO=$(basename $(git rev-parse --show-toplevel))
BRANCH=$(git branch --show-current)
TASK_DIR=~/.agent/tasks/$REPO/$BRANCH
```

Read `$TASK_DIR/SPEC.md` and `$TASK_DIR/PROGRESS.md`.

### Step 2 — Gate check

If `$TASK_DIR/SPEC.md` does not exist, scan for other specs (most recent first):

```bash
find ~/.agent/tasks -name "SPEC.md" -type f -exec stat -f "%m %N" {} \; 2>/dev/null | sort -rn | awk '{print $2}'
```

For each found SPEC.md, read its first line (title) and `## Status` field to build a list.

- If specs exist elsewhere, present them sorted by last modified (newest first):
  > "No SPEC.md for the current repo/branch. Found these specs:"
  >
  > | # | Repo / Branch | Title | Status | Last modified |
  > |---|---|---|---|---|
  > | 1 | kibana / main | Retry logic for async search | APPROVED | 2 hours ago |
  > | 2 | kibana / feature/error-handling | Improve error boundaries | IMPLEMENTING | 3 days ago |
  >
  > "Which one? (or run `crew spec` to draft a new one)"

  When the user picks one, update `TASK_DIR` to that spec's directory and continue.

- If no specs exist anywhere, stop:
  > "No specs found. Run `crew spec` first to draft one."

If the SPEC.md status is `DRAFTING`, stop:
> "The spec hasn't been approved yet. Get approval before implementing."

If the status is already `IMPLEMENTING` and PROGRESS.md has completed tasks, you're resuming — inform the user which tasks are done and which remain.

### Step 3 — Auto-recall

If `journal-search` is available, query for patterns relevant to this repo:

```bash
journal-search query "patterns and conventions for $REPO" --top 5 2>/dev/null || true
```

Also search for `pattern` type entries scoped to this repo:

```bash
rg "^\*\*Scope:\*\* $REPO" ~/.agent/journal/ -l 2>/dev/null | xargs rg "^\*\*Rule:\*\*" 2>/dev/null || true
```

Store the results as `RECALLED_PATTERNS` to pass to the subagent.

### Step 4 — Create worktree

If already on a feature branch (not `main` or the default branch), skip this step.

Otherwise, fetch the latest from the default branch and create a worktree branching from it:

```bash
DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $NF}')
git fetch origin "$DEFAULT_BRANCH"

BRANCH_NAME=<type>/<short-description>
WORKTREE_DIR=../$REPO-$(echo $BRANCH_NAME | tr '/' '-')

git worktree add -b "$BRANCH_NAME" "$WORKTREE_DIR" "origin/$DEFAULT_BRANCH"
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

1. Update `TASK_DIR` to the new branch path and move `SPEC.md` and `PROGRESS.md` there.
2. Set `WORK_DIR` to the worktree directory.

If skipped (already on feature branch), set `WORK_DIR` to the current directory.

### Step 5 — Update progress

Set PROGRESS.md to:
```
## Status: IMPLEMENTING
## Current: implement
## Next: diff-check
```

### Step 6 — Detect mode and launch worker

```bash
which ralph 2>/dev/null || which ralph.sh 2>/dev/null
```

If found and the user didn't say "implement inline", set `MODE=ralph`. Otherwise `MODE=inline`.

Launch the `@crew-builder` subagent with:
- `TASK_DIR` — the resolved task directory path
- `WORK_DIR` — the worktree or repo directory
- `RECALLED_PATTERNS` — the patterns found in Step 3 (or "none")
- `MODE` — `ralph` or `inline`
- The full contents of `SPEC.md` (so the subagent has it without needing to re-read)

### Step 7 — Handle results

When the subagent returns its Implementation Report:

**All tasks passed + quality gates passed:**
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
   > "All tasks done and quality gates pass. Ready for `crew diff`."

**Some tasks failed:**
1. Show the user which tasks failed and the error summaries from the report.
2. Ask: "Want to retry the failed tasks, skip them, or stop here?"
   - **Retry** → re-launch the subagent with only the failed tasks
   - **Skip** → proceed to diff-check with partial implementation
   - **Stop** → leave PROGRESS.md as IMPLEMENTING for later resumption

**Quality gates failed:**
1. Show the failures from the report.
2. Ask: "Want me to re-launch the worker to fix these, or do you want to fix them manually?"
   - **Re-launch** → launch subagent with instructions to fix quality gate failures
   - **Manual** → leave PROGRESS.md as IMPLEMENTING

## Rules

- Never start the subagent without a gate-checked, approved SPEC.md
- Always create the worktree before launching the subagent
- The skill handles ALL user interaction — the subagent is non-interactive
- If the subagent returns failures, always surface them to the user with options
- **Stop after quality gates pass.** Never commit, push, or create a PR.
