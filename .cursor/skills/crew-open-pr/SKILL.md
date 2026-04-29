---
name: crew-open-pr
description: "Push the current branch and open a PR with a generated description. Trigger: 'crew open pr'."
---

**Workflow**: build | **Stage**: open-pr

# Open Pull Request

## When Invoked

### Step 1: Gather context

**Check for existing PR first:**

```bash
EXISTING_PR=$(GH_PAGER=cat gh pr view --json url,number,state --jq '"#\(.number) (\(.state)): \(.url)"' 2>/dev/null)
```

If `EXISTING_PR` is non-empty, stop and report:

> "A PR already exists for this branch: $EXISTING_PR. Run `crew resolve PR` to address review comments, or push new commits directly."

Do not proceed with PR creation.

```bash
BRANCH=$(git branch --show-current)
BASE=$(git rev-parse --abbrev-ref HEAD@{upstream} 2>/dev/null | sed 's|origin/||' || echo "main")
```

Detect fork workflow using git remotes — **do not use `gh repo view`** (freezes in VS Code terminals):

```bash
_parse_repo() { echo "$1" | sed 's|.*github\.com[:/]\(.*\)\.git|\1|; s|.*github\.com[:/]\(.*\)|\1|'; }
ORIGIN_REPO=$(_parse_repo "$(git remote get-url origin 2>/dev/null)")
UPSTREAM_URL=$(git remote get-url upstream 2>/dev/null)
UPSTREAM_REPO=$(_parse_repo "$UPSTREAM_URL")
```

If `UPSTREAM_REPO` is non-empty, `origin` is a fork. Check whether the base branch exists on upstream:

```bash
if [ -n "$UPSTREAM_REPO" ]; then
  # Check if base branch exists on upstream
  if GH_PAGER=cat gh api "repos/$UPSTREAM_REPO/branches/$BASE" --silent 2>/dev/null; then
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

1. **SPEC.md** — resolve `TASK_DIR` using the canonical resolution recipe (see Session Capture block below) and read `$TASK_DIR/SPEC.md` for goal, context, and **Acceptance Criteria** (Requirements / Non-regression) to distill **reviewer-sized** "How to test" bullets (max 3–5). Read typed `## Tests` subsection headings only to mention automation (`crew test` / CI) — do not treat runbook or deprecated Manual blocks as PR reviewer steps.
2. **Commit log** — `git log $BASE..HEAD --oneline` for what was done
3. **Full diff** — `git diff $BASE...HEAD --stat` for scope; `git diff $BASE...HEAD` for details if the stat is small enough (<30 files)

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
GH_PAGER=cat gh pr create --draft --title "TITLE" --body "BODY" --base BASE --repo "$TARGET_REPO"
```

**Important:** Always pass `--body` explicitly. If `--body` is omitted or empty, `gh` opens `$EDITOR` which freezes the VS Code terminal. Never rely on interactive input for the body.

PRs are always opened as drafts. Mark ready for review manually when appropriate.

If the repo uses a PR template, read it first and fill in the sections rather than using the default format above.

### Step 4: Report back

Show the PR URL and a one-line summary.

> Next: build workflow complete. Watch for review comments — run `crew resolve PR` if they arrive.

> Run `crew log` to record this session.

## Session Capture

After creating the PR, resolve `TASK_DIR` and append to `$TASK_DIR/SESSION.md` (if found):

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

```
[TIME] crew-open-pr: PR_URL — PR_TITLE
```

Also log the transition:

```bash
~/.agent/bin/log-progress.py "$TASK_DIR" "COMMITTING → PR_OPEN ($PR_URL)"
```

Then suggest: "Want to journal this session?"

## Rules

- **Derive, don't invent.** The summary comes from SPEC.md and commits, not from re-reading the code.
- **Always ask before creating.** Show the title + description and wait for "looks good" — same pattern as crew-commit.
- **Always draft.** PRs are opened as drafts. Mark ready manually.

## Auto-clarity override

Drop to plain language before:

- Running `git push` — state the branch name, remote, and whether this is a force push; force pushes rewrite remote history
- Running `gh pr create` — show the full PR title, description, base branch, and target repo; PRs are public and trigger CI immediately
- Any fork workflow where the target repo differs from origin — call out the fork explicitly to avoid misfiling the PR

Resume compressed mode after the PR URL is returned.
