# Acting on approved threads

Step 7 detail for `crew-pr-resolver`. Loaded after the user answers the approval questions; nothing
here runs before that.

## The order is fixed

A reply says the fix is in the branch, and a thread resolved before the push sends the reviewer to a
branch that does not carry it. So:

1. Apply each approved edit and verify it.
2. Commit, then push — only when the user approved both in Step 6.
3. Reply on each approved thread.
4. Resolve it, or leave it open per its verdict.

A run stopped before the commit posts nothing: no reply, no resolution, and the handoff names the
commit as what is still owed. Skipping ahead is not a shortcut — a reply with no commit behind it is
exactly the false claim this order exists to prevent.

## Code changes

For each approved edit: apply it, then verify it before any reply claims it is fixed. Verification
uses the repository's own commands — take them from project guidance, never from a convention of the
repo you last worked in.

1. **Scope check** — `git status --porcelain` must list exactly the approved paths and nothing else. A
   path-scoped `git diff` cannot show an extra file at all, and an untracked one never appears in a
   diff: this check, not a diff, is what catches a leftover probe or an unrequested edit. A stray path
   is reverted or raised with the user, never described as part of the fix. Then confirm
   `git diff --cached --name-status` matches the approved set before the commit, so an unintended
   file cannot ride along on the `git add`.
2. **Tests** — run the narrowest test file covering each edited path. Report the command and its
   result; `no test covers <path>` is a complete answer, not a failed gate, because a review fix has
   no acceptance criteria to derive a suite from. A test that fails is reported, never made to pass by
   moving its expected value — that is the overfitting case Step 4 refuses.
3. **Lint** — the repository's lint command on the edited files.
4. **Type-check** — scoped to the affected package. **Type-check rule:** when `node_modules` is a
   symlink, follow `crew-builder`'s rule — run `tsc --noEmit -p <nearest tsconfig>`, and record it as
   skipped with that reason only when the repo has no no-emit form.

Three failed attempts at one step stop the edit: revert what was applied (`git checkout -- <file>`, or
re-apply the clean hunk), report the failure, and leave the thread open, since resolving it tells the
reviewer "handled" about work the checks contradict. Reverting matters beyond this run: an edit left in
the tree is read by the next run's Already-Addressed check as the fix. The reply says what was verified
and what was not; a check skipped without a named reason reads as a check that passed.

Read the thread and the file's diff together before replying. The edit answers that thread and
nothing beyond it; anything else it fixed goes to the user as a separate observation, not into the
reply as part of the fix.

## Commit and push

One commit for the approved edits, in the PR's worktree. `git add` only the files those edits touched.
The message follows `crew commit`'s format — `type(scope): imperative description`, one line, 72
characters at most — and names what the review asked for when that fits.

```bash
git add <approved files> && git commit -m "<type(scope): description>" && git push -u origin HEAD
```

Chain all three: `&&` between add and commit alone leaves the push to run after a rejected commit, and
the sha recorded next would be the previous tip. When any stage fails, stop — do not record a sha, do
not reply, and report which stage failed. Record the short sha only from a successful commit
(`~/.agent/bin/crew-repo-info.py --field head_short`) and check it equals the commit you just made,
because every reply quotes it.

`-u origin HEAD` on a branch with no upstream yet; plain `git push` once it tracks one. A rejected push
is reported, never forced: a non-fast-forward means another commit reached the branch, and `--force`
would discard it.

## Thread comments

Every reply is written under `~/.cursor/rules/voice.mdc`, with no exceptions: `Apply`, `Reject`, `Ask`,
`Decide`, and `Already Addressed` alike. A reply is public text under Carlos's name going to a reviewer,
so the voice rules are part of the deliverable rather than a style preference. If that file is
unreadable, stop and report it — post nothing, since a reply written without it is the failure the rule
names.

Two operations per thread (both ids come from the Step 2 query):

1. **Reply** with the draft the user approved: say what changed and why, name the check that backs it,
   or why it remains as-is. No verdict label. Put every code symbol, path, command, field, API, and
   identifier in inline backticks; leave prose unquoted. Use the thread's `id` and the first comment's
   `databaseId`:

   ```bash
   ~/.agent/bin/crew-pr-actions.py reply --repo OWNER/REPO --pr PR_NUMBER \
     --thread-id THREAD_NODE_ID --comment-id DATABASE_ID \
     --body "Fixed in <short sha>: <what changed and why>." --execute
   ```

2. **Resolve** the thread using the same node id:

   ```bash
   ~/.agent/bin/crew-pr-actions.py resolve --repo OWNER/REPO --pr PR_NUMBER \
     --thread-id THREAD_NODE_ID --execute
   ```

An `Ask` or `Decide` thread is never resolved: `Ask` gets its question as the reply, `Decide` gets the
decision named, and both stay open for the author. Edits the user excluded are not applied; threads
the user excluded are left open with no comment.

## Journal

Draft an observation only when the run produced a non-derivable lesson — what a reviewer caught that
the change missed, and why it generalises. A run that classified a thread `Decide` says so in that
entry, so a later audit can tell a design decision from a defect fix.
A resolved thread whose verdict was Apply or Adapt is the same decision the reviewer pipeline records
as an outcome, so the entry may cite it and must write nothing new for it, because the thread is the
durable record. Show the title and 1-3 paragraphs, ask `Store this journal entry? (yes / no)`, and
only on `yes` run:

```bash
~/.agent/bin/crew-mem.py journal add --title "PR review: <PR title>" --tags <tags> --repo <scope>
```

Pass the approved prose on stdin. On `no`, or when nothing qualifies, say `journal: none`. On a
non-zero exit print `warning: memory unavailable` and continue.
