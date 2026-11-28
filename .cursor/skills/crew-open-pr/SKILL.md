---
disable-model-invocation: true
name: crew-open-pr
description: "Write the PR description, then after approval ship the task (commit, push, draft PR, DONE) with crew-tool.py task-ship. Trigger: 'crew open pr'."
---

**Workflow**: build | **Stage**: open-pr

# Open Pull Request

## When Invoked

### Step 1: Gather context

**Check for existing PR first:**

```bash
EXISTING_PR=""
if PR_FACTS=$(~/.agent/bin/crew-tool.py pr-read view --fields number,state,url --field record 2>&1); then
  read -r NUMBER STATE URL < <(jq -r '"\(.number) \(.state) \(.url)"' <<<"$PR_FACTS")
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
BRANCH=$(~/.agent/bin/crew-tool.py repo-facts --field branch)
TASK_DIR=$(~/.agent/bin/crew-tool.py task-context --field task_dir)
~/.agent/bin/crew-tool.py task-context --artifacts spec,review --max-chars 6000
```

Detect fork workflow from the remotes this checkout has. Do not read the repository through `gh` at
this point — it freezes in VS Code terminals, and `repo-facts` answers both remotes locally:

```bash
ORIGIN_REPO=$(~/.agent/bin/crew-tool.py repo-facts --field origin_repo)
UPSTREAM_REPO=$(~/.agent/bin/crew-tool.py repo-facts --remote upstream --field repo)
```

**Target upstream first.** If `UPSTREAM_REPO` is non-empty, `origin` is a fork and the PR targets
`upstream`. Only when there is no `upstream` remote does the PR target `origin`. Resolve `BASE` from
the repo the PR will target: the default branch of `upstream` for a fork, otherwise of `origin`.

```bash
BASE=$(~/.agent/bin/crew-tool.py repo-facts --network --remote "$([ -n "$UPSTREAM_REPO" ] && echo upstream || echo origin)" --field default_branch)
```

```bash
TARGET_REPO="${UPSTREAM_REPO:-$ORIGIN_REPO}"
```

**Stack gate.** `BASE` is the default branch (the value resolved above)
unless SPEC.md `## Base:` names a parent branch; do not ask whether the branch stacks. A base that fully matches (whole branch name) a `landing_bases` pattern from the repo's
`AGENTS.md` (release branches such as `9.x`; format in `src/crew/AGENTS.md`) is a normal base:
no stack message, no question, and say "Base is X (landing base)" once. With no `landing_bases` the
default branch only is normal. For any other base, print exactly this one line and ask once:

> Base is X, not <default>. Merging this lands the change in X only. Merge order: #a -> #b -> <default>. Reply `stack` to open it or `<default>` to retarget.

`stack` keeps the named base; `<default>` retargets to the default branch. List in the merge order
only PRs that exist (look them up); with none, omit the clause. An autonomous run stops with that
line at the top of the final message and opens nothing, after running
`crew-tool.py task-transition block "$TASK_DIR" --reason "<reason>"`. With an `upstream` remote, a non-default base must exist there, so check; if it
does not, the PR cannot target upstream. Say so, and switch to `origin` only after the user confirms:

```bash
if [ -n "$UPSTREAM_REPO" ] && [ "$BASE" != "$(~/.agent/bin/crew-tool.py repo-facts --remote upstream --field default_branch)" ]; then
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

### Step 3: Approve, then ship

`BASE` and `TARGET_REPO` come from Step 1. Show the title, description, `BASE`, and `TARGET_REPO`,
and wait for approval (Gate 2); nothing is committed or pushed before it. A `BASE` that is neither
the default branch nor a landing base passes the Step 1 stack gate first. When
`$TASK_DIR/REPORT.md` exists, show the builder's unverified claims in the confirmation (the full list
stays in REPORT.md):

```bash
~/.agent/bin/crew-verify.py report-check "$TASK_DIR/REPORT.md" --unverified 5
```

Title format: a conventional commit line (`type(scope): description`, 72 characters at most); it is
both the commit message and the PR title. If the repo uses a PR template, fill in its sections
rather than the default format. After approval, write the approved description to a file `BODY`
(`$TASK_DIR/artifacts/pr-body.md`; with no task, a temporary file) and run, with `ATTRIBUTION` set to
the commit attribution line your harness gives (empty when it gives none; ship then uses its
default). `TARGET` is `--task-dir "$TASK_DIR"`, or empty when `TASK_DIR` is empty (run it from the
checkout to ship; there is no `mark-done`). If `task-context` failed, stop and report instead.

```bash
~/.agent/bin/crew-tool.py task-ship "TITLE" "$BODY" "$BASE" "$TARGET_REPO" $TARGET --attribution "$ATTRIBUTION"
```

`ship` is the one way a task is committed and its PR opened. It runs in the task's recorded worktree
and never asks: it stages tracked changes and untracked files git does not ignore, commits (after
the same credential scan the commit hook runs), merges the base, re-runs the spec's `## Tests`
commands, pushes (never forced), opens or reuses the draft PR, and runs `mark-done`. Each finished
step is a `SHIP` entry in PROGRESS.md for that branch. A program (one PR per phase) ships every
phase but the last with `--phase` after `TARGET`: the PR is recorded, the task stays `IMPLEMENTING`,
and later phases' boxes may stay open. The last phase uses plain `ship`.

- **Exit 0** prints `shipped: <task> <PR URL>`; keep the URL for Step 4.
- **Exit 1** prints `error: ship stopped at <step>: <reason>`: a risky file or a credential, a merge
  conflict, a failing or hanging test, files the tests wrote, a push or `gh` failure, or a
  `mark-done` refusal. Show it in full. Once the cause is fixed (a fix is a new commit, never an
  amend), run the same command again: it re-checks the finished steps and resumes.
- **Exit 2** means nothing ran: the task is not `IMPLEMENTING`, its worktree is missing, on another
  branch or of another repository, `mark-done` would refuse it, or `BASE` or `TARGET_REPO` differ
  from ship's own resolution (the spec's `## Base:`, else the default branch of the remote whose
  repository is `TARGET_REPO`). Report the `error:` line; do not retry with other values unless
  the user approves them.

PRs are always opened as drafts; the user marks them ready. Do not publish review comments, inline
findings, or review summaries before `ship` has pushed.

### Step 4: Report back

Show the PR URL and a one-line summary.

## Session Capture

For a PR that already existed (Step 1), record it and mark the task `DONE`: a task is done once a PR
for it is open. `mark-done` adds the URL to the task's PR list and refuses unless the spec is
`IMPLEMENTING`, every criterion is checked, and a review's `Reviewed at:` commit is an ancestor of
HEAD:

```bash
[ -n "$TASK_DIR" ] && ~/.agent/bin/crew-tool.py task-transition done "$TASK_DIR" --pr-url "$PR_URL"
```

Show a refusal's `error:` line with its reason and the PR URL, and say the task is not marked done.

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

- Running `ship` — show the full PR title, description, branch, base branch, and target repo; it
  pushes and opens a PR, which is public and triggers CI immediately
- Any fork workflow where the target repo differs from origin — call out the fork explicitly to
  avoid misfiling the PR

Continue after the PR URL is returned. The build workflow is complete at that point; review comments
arrive on the PR.

> Next: run `crew resolve PR` when review comments arrive.
