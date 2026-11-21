# Completion handoff

Step 7's post-implementation writes, after every task passed. Both are drafts: nothing durable is
written without the user's explicit approval (`memory-capture.mdc`).

## Journal entry (draft, never automatic)

Draft an immutable observation only when it holds something non-derivable from code, git, or the
spec: a decision that will constrain future work, or a surprise with a lesson. Derive it from SPEC.md
and REPORT.md:

- what was built and why it matters;
- what broke or surprised during implementation — omit when the report has no structural
  observations;
- patterns or constraints worth remembering — omit when nothing is new.

Show the title and one to three plain-prose paragraphs, each a self-contained idea, then ask `Store
this journal entry? (yes / no)`. Only on `yes`, run `~/.agent/bin/crew-mem.py journal add --title
"Implemented: <title>" --tags <tags> --repo <scope>` with the prose on stdin. On `no`, or when
nothing qualifies, write nothing and report `journal: none`. On a non-zero exit print `warning: memory
unavailable` and continue.

## Memory candidates

Inspect the completed spec, the report, the verification output, and the journal entry. Draft zero to
three typed candidates into `~/.agent/memory/.inbox/` only when each is durable, non-derivable, and
backed by a file, command, or journal evidence pointer. Do not import them. Show each candidate (or
`none`) in the completion handoff and ask for one batch approval; `crew memory seed` or
`crew-mem.py import-inbox` performs the later promotion.
