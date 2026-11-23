# Acting on approved threads

Step 7 detail for `crew-pr-resolver`. Loaded after the user answers the approval questions; nothing
here runs before that.

## Code changes

For each approved edit: apply it, run lints on the edited files, and run a type-check scoped to the
affected package. **Type-check rule:** when `node_modules` is a symlink, follow `crew-builder`'s rule —
run `tsc --noEmit -p <nearest tsconfig>`, and record it as skipped with that reason only when the repo
has no no-emit form.

## Thread comments

For each approved thread, two operations (both ids come from the Step 2 query). Read
`~/.cursor/rules/voice.mdc` first and apply it: PR review replies are written under Carlos's name. If
that file is unreadable, stop and report.

1. **Reply**: say what changed and why, or why it remains as-is. No verdict label. Put every code
   symbol, path, command, field, API, and identifier in inline backticks; leave prose unquoted. Use
   the thread's `id` and the first comment's `databaseId`:

   ```bash
   ~/.agent/bin/crew-pr-actions.py reply --repo OWNER/REPO --pr PR_NUMBER \
     --thread-id THREAD_NODE_ID --comment-id DATABASE_ID \
     --body "Fixed in <commit>: <what changed and why>." --execute
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
the change missed, and why it generalises. Show the title and 1-3 paragraphs, ask
`Store this journal entry? (yes / no)`, and only on `yes` run:

```bash
~/.agent/bin/crew-mem.py journal add --title "PR review: <PR title>" --tags <tags> --repo <scope>
```

Pass the approved prose on stdin. On `no`, or when nothing qualifies, say `journal: none`. On a
non-zero exit print `warning: memory unavailable` and continue.
