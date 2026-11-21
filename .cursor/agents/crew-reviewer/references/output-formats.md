# Review output and handoff

Emit `## Review: <mode> — <summary>`, followed by one flat numbered list of anchored findings in the
format [finding formats](finding-formats.md) defines. No severity sections.

- A self-review with no blocking findings states `PASS` or `WARN` and ends with `Next: run \`crew
  commit\` to continue.`
- A blocked self-review states `BLOCK` and ends with `Next: run \`crew review address\` to resolve the
  findings.`

A finding line carries its kind beside its label when one was recorded:

```
1. [attention] · security **`path/to/file.ts — line N`** — one-line title
```

The kind is optional: a finding with no clear kind omits the suffix rather than inventing a value.

## Render the report, do not re-author it

The reply is the persisted `report.md` passed through unchanged under its `## Review:` heading. Do not
summarize, re-word, or rebuild it from your notes: every finding already carries its `file:line`
anchor, its label, and the code snippet the format requires, and a rewrite is how those snippets get
dropped.

A reply showing findings as prose with inline `` `file:line` `` and no fenced block has failed this
step even when `report.md` on disk is correct. Before sending, check that the reply holds every fence
`report.md` holds and that each `[blocking]` finding shows its anchored snippet.

## Do not write the generated sections

`persist` appends `### Coverage by layer` and `### Files reviewed` itself, from the layer map and
`--files`. Write the report body — heading, findings, verdict, next step — but not those two sections:
a report carrying either as a real heading is rejected rather than merged, so it cannot appear twice
with the reader unable to tell which copy is authoritative. Quoting a heading inside a finding, or
using a deeper `####` heading, is not a duplicate.
