# Reporting a run

Step 6 detail for `crew-pr-resolver`. The report is the run's output: it states what happened to every
unresolved thread, and it goes out even when nothing could be applied.

## Outdated threads

A thread with `isOutdated: true` and `isResolved: false` is read-only — propose no edit and resolve
nothing. List it in the same table shape so the reader sees it was evaluated:

| # | File | Reviewer | Note |
|---|------|----------|------|
| 1 | path/to/file.ts:42 | @reviewer | Outdated — verify the concern still applies. |

## Summary line

One line under the table, counts only, in this order:

```
N apply / N adapt / N decide / N reject / N ask / N defer / N addressed
```

## Why the section exists

A run that proposes no edit still evaluated every thread, and the reader cannot tell a clean PR from a
skipped check without the table. That is why the report is published unconditionally: the counts may
all read zero, and that zero is the answer.
