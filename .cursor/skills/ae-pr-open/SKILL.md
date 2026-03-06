---
name: ae-pr-open
description: "Push the current branch and open a PR with a generated description. Use when the user says 'open a PR', 'create PR', 'push and open PR', or 'ready to push'."
---

# Open Pull Request

## When Invoked

### Step 1: Gather context

```bash
BRANCH=$(git branch --show-current)
BASE=$(git rev-parse --abbrev-ref HEAD@{upstream} 2>/dev/null | sed 's|origin/||' || echo "main")
```

Read these sources (in order of priority):

1. **SPEC.md** — `~/.agent/tasks/$(basename $(git rev-parse --show-toplevel))/$BRANCH/SPEC.md` for goal, context, acceptance criteria
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
🤖
```

After approval:

```bash
gh pr create --draft --title "TITLE" --body "BODY" --base BASE
```

PRs are always opened as drafts. Mark ready for review manually when appropriate.

If the repo uses a PR template, read it first and fill in the sections rather than using the default format above.

### Step 4: Report back

Show the PR URL and a one-line summary.

## Rules

- **Derive, don't invent.** The summary comes from SPEC.md and commits, not from re-reading the code.
- **Always ask before creating.** Show the title + description and wait for "looks good" — same pattern as ae-commit.
- **Always draft.** PRs are opened as drafts. Mark ready manually.
