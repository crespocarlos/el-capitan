---
name: crew-open-pr
description: "Push the current branch and open a PR with a generated description. Trigger: 'crew open pr'."
---

# Open Pull Request

## When Invoked

### Step 1: Gather context

```bash
BRANCH=$(git branch --show-current)
BASE=$(git rev-parse --abbrev-ref HEAD@{upstream} 2>/dev/null | sed 's|origin/||' || echo "main")
```

Detect fork workflow:

```bash
UPSTREAM_REPO=$(gh repo view --json parent --jq '.parent.owner.login + "/" + .parent.name' 2>/dev/null)
```

If `UPSTREAM_REPO` is non-empty, `origin` is a fork. The PR should target the upstream repo. Set:

```bash
TARGET_REPO="$UPSTREAM_REPO"
```

If empty (not a fork), the PR targets the current repo:

```bash
TARGET_REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner')
```

Read these sources (in order of priority):

1. **SPEC.md** — find the active spec under `~/.agent/tasks/$(basename $(git rev-parse --show-toplevel))/$BRANCH/*/SPEC.md` (non-DONE, most recent; fall back to `.../$BRANCH/SPEC.md` for old flat layout) for goal, context, acceptance criteria
2. **Commit log** — `git log $BASE..HEAD --oneline` for what was done
3. **Full diff** — `git diff $BASE...HEAD --stat` for scope; `git diff $BASE...HEAD` for details if the stat is small enough (<30 files)

### Step 2: Generate the description

Use the template in [pr-template.md](./references/pr-template.md). If the repo has its own `.github/PULL_REQUEST_TEMPLATE.md`, fill that in instead.

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

## Session Capture

After creating the PR, resolve `TASK_DIR` and append to `$TASK_DIR/SESSION.md` (if found):

```bash
BRANCH_DIR=~/.agent/tasks/$(basename $(git rev-parse --show-toplevel))/$(git branch --show-current)
# TASK_DIR = parent of the active (non-DONE) SPEC.md under $BRANCH_DIR/*/
# Fall back to $BRANCH_DIR if SPEC.md exists there (old flat layout)
```

```
[TIME] crew-open-pr: PR_URL — PR_TITLE
```

Then suggest: "Want to journal this session?"

## Rules

- **Derive, don't invent.** The summary comes from SPEC.md and commits, not from re-reading the code.
- **Always ask before creating.** Show the title + description and wait for "looks good" — same pattern as crew-commit.
- **Always draft.** PRs are opened as drafts. Mark ready manually.
