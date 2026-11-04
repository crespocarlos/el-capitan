---
disable-model-invocation: true
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

> "A PR already exists for this branch: $EXISTING_PR. Run `crew resolve PR` to address review
> comments, or push new commits directly."

Do not proceed with PR creation.

```bash
BRANCH=$(git branch --show-current)
```

Detect fork workflow using git remotes — **do not use `gh repo view`** (freezes in VS Code
terminals):

```bash
_parse_repo() { echo "$1" | sed 's|.*github\.com[:/]\(.*\)\.git|\1|; s|.*github\.com[:/]\(.*\)|\1|'; }
ORIGIN_REPO=$(_parse_repo "$(git remote get-url origin 2>/dev/null)")
UPSTREAM_URL=$(git remote get-url upstream 2>/dev/null)
UPSTREAM_REPO=$(_parse_repo "$UPSTREAM_URL")
```

**Target upstream first.** If `UPSTREAM_REPO` is non-empty, `origin` is a fork and the PR targets
`upstream`. Only when there is no `upstream` remote does the PR target `origin`. Resolve `BASE` from
the repo the PR will target: the default branch of `upstream` for a fork, otherwise of `origin`.

```bash
BASE=$(~/.agent/bin/default-branch.sh "$([ -n "$UPSTREAM_REPO" ] && echo upstream || echo origin)")
```

```bash
TARGET_REPO="${UPSTREAM_REPO:-$ORIGIN_REPO}"
```

Ask: "Does this branch stack on another branch? If so, name it." If it does, set `BASE` to that
branch. With an `upstream` remote, that base must exist there, so check; if it does not, the PR
cannot target upstream. Say so, and switch to `origin` only after the user confirms:

```bash
if [ -n "$UPSTREAM_REPO" ] && [ "$BASE" != "$(~/.agent/bin/default-branch.sh upstream)" ]; then
  GH_PAGER=cat gh api "repos/$UPSTREAM_REPO/branches/$BASE" --silent 2>/dev/null \
    || echo "BASE '$BASE' not found on $UPSTREAM_REPO (or the check failed); ask before targeting $ORIGIN_REPO"
fi
```

Read these sources (in order of priority):

1. **SPEC.md** — resolve `TASK_DIR` using the canonical resolution recipe (see Session Capture block
   below) and read `$TASK_DIR/SPEC.md` for goal, context, and **Acceptance criteria** to distill
   **reviewer-sized** "How to test" bullets (max 3–5). Read typed `## Tests` subsection headings
   only to mention automation (`crew test` / CI).
2. **Commit log** — `git log $BASE..HEAD --oneline` for what was done
3. **Full diff** — `git diff $BASE...HEAD --stat` for scope; `git diff $BASE...HEAD` for details if
   the stat is small enough (<30 files)

### Step 2: Generate the description

Use the template in [pr-template.md](./references/pr-template.md)

Enforce summary quality:
- Write `## Summary` as human prose, not a change-log dump.
- Lead with user-visible behavior and outcome; include implementation detail only if it clarifies
  risk/scope.
- Gate length to the change size (see the template) — small changes get a sentence or two; only
  large, cross-cutting work warrants a second paragraph.
- Do not group the summary by layer with per-file rename lists.

### Step 3: Approve, push, and create the PR

`BASE` and `TARGET_REPO` come from Step 1. Show the title, description, `BASE`, and `TARGET_REPO`,
and wait for approval before running the push. Do not push before approval.

```bash
git push -u origin HEAD
```

This push is a hard ordering boundary: do not publish review comments, inline findings, or review
summaries before it succeeds. After pushing, re-fetch the remote head SHA and use that SHA as the
only commit identity for any subsequent PR comment publication.

Present the title and description to the user. Title format: same as the primary commit message, or
a summary if there are multiple commits.

After approval:

```bash
PR_URL=$(GH_PAGER=cat gh pr create --draft --title "TITLE" --body "BODY" --base BASE --repo "$TARGET_REPO")
```

`gh pr create` prints the PR URL; keep it as `PR_URL` for Step 4 and Session Capture.

**Important:** Always pass `--body` explicitly. If `--body` is omitted or empty, `gh` opens
`$EDITOR` which freezes the VS Code terminal. Never rely on interactive input for the body.

PRs are always opened as drafts. Mark ready for review manually when appropriate.

If the repo uses a PR template, read it first and fill in the sections rather than using the default
format above.

### Step 4: Report back

Show the PR URL and a one-line summary.

> Next: build workflow complete. Watch for review comments — run `crew resolve PR` if they arrive.

## Session Capture

After creating the PR, resolve `TASK_DIR`:

```bash
source ~/.agent/bin/task-env.sh
```

If `TASK_DIR` is non-empty, set the spec to `done` and log the transition. `--mark-done` writes the
status and appends to `PROGRESS.md`; it refuses unless the spec is `IMPLEMENTING`, all criteria are
checked, the last review verdict is pass or warn, and the task branch matches the current branch:

```bash
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/crew-ls.py --mark-done "$TASK_DIR" --pr-url "$PR_URL" \
    --branch "$(git rev-parse --abbrev-ref HEAD)" \
    || echo "warning: PR opened but spec not marked done" >&2
fi
```

On a non-zero exit, show the `error:` line and the PR URL, and say the spec is not marked done. Do not
re-run `gh pr create`. Once the cause is fixed, re-run the same `--mark-done` command; `--force`
skips the evidence checks only when the user asks for it. With no `TASK_DIR` (for example `crew
quick`), there is nothing to mark.

**Journal (opt-in, never automatic).** Memory writes need explicit approval (`memory-capture.mdc`;
`CLAUDE.md`: do not write memories automatically). After the PR is open, draft an observation only
when it holds something non-derivable: a key architectural decision, or a lesson for future similar
work. Derive it from SPEC.md when a task exists, otherwise from the commit log and PR description;
1-2 plain-prose paragraphs, each one self-contained idea. Show the title and prose and ask `Store
this journal entry? (yes / no)`. Only on `yes`, run `~/.agent/bin/mem.py journal add --title "PR
opened: <title>" --tags <tags> --repo <scope>` with the prose on stdin (heredoc). On `no`, or when
nothing qualifies, write nothing and say `journal: none`. On non-zero exit print `warning: memory
unavailable` and continue.

## Rules

- **Derive, don't invent.** The summary comes from SPEC.md and commits, not from re-reading the
  code.
- **Narrative over inventory.** Explain behavior and intent in prose; avoid laundry lists of renamed
  files/fields/steps.
- **Always ask before creating.** Show the title + description and wait for "looks good" — same
  pattern as crew-commit.
- **Always draft.** PRs are opened as drafts. Mark ready manually.

## Plain-language gates

Use plain language, without compressed summaries, before:

- Running `git push` — state the branch name, remote, and whether this is a force push; force pushes
  rewrite remote history
- Running `gh pr create` — show the full PR title, description, base branch, and target repo; PRs
  are public and trigger CI immediately
- Any fork workflow where the target repo differs from origin — call out the fork explicitly to
  avoid misfiling the PR

Continue after the PR URL is returned.
