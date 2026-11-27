# Reporting a run

Step 6 detail for `crew-pr-resolver`. The report is the run's output: it states what happened to every
unresolved thread, and it goes out even when nothing could be applied.

## Outdated threads

A thread with `isOutdated: true` and `isResolved: false` is read-only — propose no edit and resolve
nothing. List it in the same table shape so the reader sees it was evaluated:

| # | File | Reviewer | Note |
|---|------|----------|------|
| 1 | path/to/file.ts:42 | @reviewer | Outdated — verify the concern still applies. |

## Replies a table cell cannot hold

A Markdown table cell ends at `|`, so a proposed reply containing one — a quoted expression, a type
union, a copied pipe-separated query — is split across two columns and the reader sees
a truncated thread. When a reply carries a `|`, put it in a fenced block beneath the table, labelled
with its `#`, and let the cell read `see below`. The same applies to any reply that needs a second
line: a cell cannot hold one either.

## Summary line

One line under the table, counts only, in this order:

```
N apply / N adapt / N decide / N reject / N ask / N defer / N addressed
```

## Journal draft

Under the summary line, draft a journal entry only when the run produced a non-derivable lesson: what
a reviewer caught that the change missed, and why it generalises. A run that classified a thread
`Decide` says so, so a later audit can tell a design decision from a defect fix. An Apply or Adapt
thread is already recorded by the thread itself, so the entry may cite it and adds nothing new for
it. Show the title (`PR review: <PR title>`) and one to three paragraphs, or `journal: none`; the
Step 6 question's `+ journal` stores it.

## Why the section exists

A run that proposes no edit still evaluated every thread, and the reader cannot tell a clean PR from a
skipped check without the table. That is why the report is published unconditionally: the counts may
all read zero, and that zero is the answer.
