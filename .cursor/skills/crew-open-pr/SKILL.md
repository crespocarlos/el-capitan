---
name: crew-open-pr
description: "Push the current branch and open a PR with a generated description. Trigger: 'crew open pr'."
---
**Workflow**: build | **Stage**: open-pr

# Open Pull Request

## When Invoked

### Step 1: Gather context

```bash
BRANCH=$(git branch --show-current)
BASE=$(git rev-parse --abbrev-ref HEAD@{upstream} 2>/dev/null | sed 's|origin/||' || echo "main")
```

Detect fork workflow and determine target repo:

```bash
UPSTREAM_REPO=$(gh repo view --json parent --jq '.parent.owner.login + "/" + .parent.name' 2>/dev/null)
ORIGIN_REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null)
```

If `UPSTREAM_REPO` is non-empty, `origin` is a fork. Check whether the base branch exists on upstream:

```bash
if [ -n "$UPSTREAM_REPO" ]; then
  # Check if base branch exists on upstream
  if gh api "repos/$UPSTREAM_REPO/branches/$BASE" --silent 2>/dev/null; then
    TARGET_REPO="$UPSTREAM_REPO"
  else
    # Base branch only exists on the fork — target the fork
    TARGET_REPO="$ORIGIN_REPO"
  fi
else
  TARGET_REPO="$ORIGIN_REPO"
fi
```

This handles the common case where feature branches are based on other feature branches in your fork, not on upstream's main.

Read these sources (in order of priority):

1. **SPEC.md** — resolve `TASK_DIR` using the canonical resolution recipe (see Session Capture block below) and read `$TASK_DIR/SPEC.md` for goal, context, acceptance criteria, and `## Tests > ### Manual` section
2. **Runbook** — check for `$TASK_DIR/runbook.md`; if present, note its path for the "How to test" section
3. **Commit log** — `git log $BASE..HEAD --oneline` for what was done
4. **Full diff** — `git diff $BASE...HEAD --stat` for scope; `git diff $BASE...HEAD` for details if the stat is small enough (<30 files)

### Step 2: Generate the description

Use the template in [pr-template.md](./references/pr-template.md)

### Step 3: Push and create the PR

```bash
git push -u origin HEAD
```

Present the title and description to the user. Title format: same as the primary commit message, or a summary if there are multiple commits.

Before creating, ask: **"Did you use LLM assistance for this PR?"** If yes, append to the end of the description body:

```
---
🤖 Co-authored with AI assistance.
```

After approval:

```bash
gh pr create --draft --title "TITLE" --body "BODY" --base BASE --repo "$TARGET_REPO"
```

PRs are always opened as drafts. Mark ready for review manually when appropriate.

If the repo uses a PR template, read it first and fill in the sections rather than using the default format above.

### Step 4: Report back

Show the PR URL and a one-line summary.

> Next: build workflow complete. Watch for review comments — run `crew resolve PR` if they arrive.

## Session Capture

After creating the PR, resolve `TASK_DIR` and append to `$TASK_DIR/SESSION.md` (if found):

```bash
TASK_DIR=$(~/.agent/tools/resolve-task-dir.sh 2>/dev/null || echo "")
```

```
[TIME] crew-open-pr: PR_URL — PR_TITLE
```

Also log the transition:

```bash
~/.agent/tools/log-progress.sh "$TASK_DIR" "COMMITTING → PR_OPEN ($PR_URL)"
```

Then suggest: "Want to journal this session?"

## Rules

- **Derive, don't invent.** The summary comes from SPEC.md and commits, not from re-reading the code.
- **Always ask before creating.** Show the title + description and wait for "looks good" — same pattern as crew-commit.
- **Always draft.** PRs are opened as drafts. Mark ready manually.
