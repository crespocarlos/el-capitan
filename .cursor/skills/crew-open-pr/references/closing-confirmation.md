# Closing confirmation

The one memory question of the build workflow, asked after `crew open pr` has opened the PR. Earlier
stages only draft: `crew implement` writes memory drafts to the inbox and the stop hook queues a
review, and neither asks. Nothing durable is written without this answer (`memory-capture.mdc`).

## Gather

- **Journal draft.** Draft one only when it holds something non-derivable from code, git, or the spec:
  a decision that will constrain future work, or a surprise with a lesson. Derive it from SPEC.md and
  REPORT.md when a task exists, otherwise from the commit log and PR description: a title
  `PR opened: <title>` and one to three plain-prose paragraphs, each a self-contained idea.
- **Memory drafts.** Only the drafts this run wrote: `~/.agent/bin/crew-inbox.py --json --since
  <start>`, where `<start>` is `created_at` from the task's `.task-id`, or without a task the time of
  the branch's first commit (`git log --reverse --format=%cI <base>..HEAD`, first line). Older drafts
  are counted in `older` and left out: they belong to the next session start's inbox listing. Run
  `~/.agent/bin/crew-mem.py consolidate --dry-run` so a draft that repeats an existing memory is shown
  as such, not as new.

With neither, report `journal: none, memory: none` and ask nothing.

## Ask once

Show the journal draft, then the drafts under the label `memory drafts written since <start>:`, each
as its file name, type, and one-line lesson; when `older` is above zero, add
`<older> older draft(s) not shown`. Then ask one question:

```text
decision-required: store the journal entry and the memory drafts listed above?
options:
 - 1: journal and every listed draft
 - 2: journal only
 - 3: listed drafts only
 - 4: choose: name the drafts to import, and say whether the journal goes too
 - 5: neither
recommendation: <the option that stores what holds a non-derivable lesson; name the drafts that repeat an existing memory or are thin>
default: 5
```

Omit the options that name a part with nothing in it.

## Act on the answer

- Journal: `~/.agent/bin/crew-mem.py journal add --title "PR opened: <title>" --tags <tags> --repo
  <scope>` with the approved prose on stdin.
- Drafts: `~/.agent/bin/crew-mem.py import-inbox <file> ...`, naming each approved file, never the
  bare form (`memory-capture.mdc`).
- A part the user declined is not written. Name the declined drafts and offer once to discard them
  (`rm ~/.agent/memory/.inbox/<file> ...`); kept ones stay in the inbox for `crew memory`.
- Then run `~/.agent/bin/crew-inbox.py --drain`: it clears the stop hook's review queue, so the next
  session start does not ask the same question again; it leaves the drafts alone.
- Exit 2 from either memory command: print `warning: memory unavailable` and continue; the PR is
  already open, so a memory failure never undoes the stage.
