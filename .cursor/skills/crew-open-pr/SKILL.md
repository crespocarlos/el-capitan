---
disable-model-invocation: true
name: crew-open-pr
description: "Push the current branch, open a PR with a generated description, and mark the task DONE. Trigger: 'crew open pr'."
---

**Workflow**: build | **Stage**: open-pr

# Open Pull Request

## When Invoked

### Step 1: Gather context

**Check for existing PR first:**

```bash
EXISTING_PR=""
if PR_FACTS=$(~/.agent/bin/crew-pr-actions.py view --field number,state,url 2>&1); then
  { read -r NUMBER; read -r STATE; read -r URL; } <<<"$PR_FACTS"
  EXISTING_PR="#$NUMBER ($STATE): $URL"
fi
```

A nonzero exit here is the ordinary case — no PR exists for this branch yet — so it empties
`EXISTING_PR` rather than stopping. Any other failure looks the same, which is why the PR-create step
below still reports what `gh` says.

If `EXISTING_PR` is non-empty, the PR was opened another way (by hand, or by an earlier run that
stopped). Run [Session Capture](#session-capture) with `PR_URL=$URL`, so the task records it and is
marked done now rather than at a later session start, then stop and report:

> "A PR already exists for this branch: $EXISTING_PR. Run `crew resolve PR` to address review
> comments, or push new commits directly."

Do not proceed with PR creation.

```bash
BRANCH=$(~/.agent/bin/crew-repo-info.py --field branch)
source ~/.agent/bin/task-env.sh
~/.agent/bin/crew-task-context.py --artifacts spec,review --max-chars 6000
```

Detect fork workflow from the remotes this checkout has. Do not read the repository through `gh` at
this point — it freezes in VS Code terminals, and `crew-repo-info.py` answers both remotes locally:

```bash
ORIGIN_REPO=$(~/.agent/bin/crew-repo-info.py --field origin_repo)
UPSTREAM_REPO=$(~/.agent/bin/crew-repo-info.py --remote upstream --field repo)
```

**Target upstream first.** If `UPSTREAM_REPO` is non-empty, `origin` is a fork and the PR targets
`upstream`. Only when there is no `upstream` remote does the PR target `origin`. Resolve `BASE` from
the repo the PR will target: the default branch of `upstream` for a fork, otherwise of `origin`.

```bash
BASE=$(~/.agent/bin/crew-repo-info.py --network --remote "$([ -n "$UPSTREAM_REPO" ] && echo upstream || echo origin)" --field default_branch)
```

```bash
TARGET_REPO="${UPSTREAM_REPO:-$ORIGIN_REPO}"
```

**Stack gate.** `BASE` is the default branch (the value resolved above)
unless SPEC.md `## Base:` names a parent branch; do not ask whether the branch stacks. A base that fully matches (whole branch name) a `landing_bases` pattern from the repo's
`AGENTS.md` (release branches such as `9.x`; format in `.agent/tools/AGENTS.md`) is a normal base:
no stack message, no question, and say "Base is X (landing base)" once. With no `landing_bases` the
default branch only is normal. For any other base, print exactly this one line and ask once:

> Base is X, not <default>. Merging this lands the change in X only. Merge order: #a -> #b -> <default>. Reply `stack` to open it or `<default>` to retarget.

`stack` keeps the named base; `<default>` retargets to the default branch. List in the merge order
only PRs that exist (look them up); with none, omit the clause. An autonomous run stops with that
line at the top of the final message and opens nothing, after running
`crew-task.py blocked "$TASK_DIR" "<reason>"`. With an `upstream` remote, a non-default base must exist there, so check; if it
does not, the PR cannot target upstream. Say so, and switch to `origin` only after the user confirms:

```bash
if [ -n "$UPSTREAM_REPO" ] && [ "$BASE" != "$(~/.agent/bin/crew-repo-info.py --remote upstream --field default_branch)" ]; then
  GH_PAGER=cat gh api "repos/$UPSTREAM_REPO/branches/$BASE" --silent 2>/dev/null \
    || echo "BASE '$BASE' not found on $UPSTREAM_REPO (or the check failed); ask before targeting $ORIGIN_REPO"
fi
```

Read these sources (in order of priority):

1. **SPEC.md** — use the returned SPEC.md when present for goal, context, and **Acceptance
   criteria** to distill **reviewer-sized** "How to test" bullets (max 3–5). Read typed `## Tests`
   subsection headings only to mention automation (the builder's verification / CI).
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
and wait for approval before running the push. Do not push before approval. A `BASE` that is
neither the default branch nor a landing base passes the Step 1 stack gate first; never open the PR
against it without that answer. When
`$TASK_DIR/REPORT.md` exists, show the builder's unverified claims in the confirmation (the full list
stays in REPORT.md):

```bash
~/.agent/bin/crew-verify.py report-check "$TASK_DIR/REPORT.md" --unverified 5
```

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

## Session Capture

After creating the PR, resolve `TASK_DIR`:

```bash
source ~/.agent/bin/task-env.sh
```

If `TASK_DIR` is non-empty, record the PR and mark the task `DONE`: a task is done once a PR for it is
open, and the review cycle and the merge happen after. `mark-done` adds the PR URL to the task's PR
list (a task can hold several; on a task already `DONE` it only adds the URL), writes the status and
appends to `PROGRESS.md`. It refuses unless the spec is `IMPLEMENTING`, every criterion is checked,
and, when a review exists, its `Reviewed at:` commit is an ancestor of HEAD. Because `crew commit`
runs after `crew review`, HEAD is normally ahead of the reviewed tree; a review older than a rebase
must be re-run.

```bash
if [ "${CREW_TASK_STATE:-ok}" = "error" ]; then
  echo "error: task state unreadable; PR opened ($PR_URL) but the task is not marked done" >&2
  exit 1
elif [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/crew-task.py mark-done "$TASK_DIR" --pr-url "$PR_URL" \
    || { echo "error: PR opened ($PR_URL) but the task is not marked done" >&2; exit 1; }
else
  LIKELY=$(~/.agent/bin/crew-ls.py --json --status implementing --max-chars 1000000 \
    | jq -r 'sort_by(.activity_days) | .[0].directory // "<TASK_DIR>"')
  echo "note: no task matches this branch; to attach $PR_URL to one: ~/.agent/bin/crew-task.py mark-done $LIKELY --pr-url $PR_URL (newest IMPLEMENTING task of this repo; check it is the right one)"
fi
```

A refusal ends the stage with a non-zero exit: show the `error:` line with its reason and the PR URL,
and say the task is not marked done. The PR stays recorded in the task. Do not re-run `gh pr create`.
Once the cause is fixed, re-run the same `mark-done` command; `--force` skips the evidence checks only
when the user asks for it. With no matching task, as when one task ships through PRs on several
branches, show the `note:` line as printed and run that command only when the user confirms the task.

**Closing confirmation.** Last, ask the one journal and memory question of the workflow per
[closing confirmation](references/closing-confirmation.md); it is the build workflow's only place
either is asked (the respond workflow's is `crew-pr-resolver`'s `+ journal`).

## Rules

- **Derive, don't invent.** The summary comes from SPEC.md and commits, not from re-reading the
  code.
- **Narrative over inventory.** Explain behavior and intent in prose; avoid laundry lists of renamed
  files/fields/steps.
- **Ask before creating.** Show the title + description and wait for "looks good" — same pattern as
  crew-commit.
- **Open as a draft.** The user marks it ready.

## Plain-language gates

Use plain language, without compressed summaries, before:

- Running `git push` — state the branch name, remote, and whether this is a force push; force pushes
  rewrite remote history
- Running `gh pr create` — show the full PR title, description, base branch, and target repo; PRs
  are public and trigger CI immediately
- Any fork workflow where the target repo differs from origin — call out the fork explicitly to
  avoid misfiling the PR

Continue after the PR URL is returned. The build workflow is complete at that point; review comments
arrive on the PR.

> Next: run `crew resolve PR` when review comments arrive.
