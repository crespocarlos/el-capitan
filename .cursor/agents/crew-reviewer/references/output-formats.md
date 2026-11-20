# Review output and handoff

Emit `## Review: <mode> — <summary>`, followed by one flat numbered list of anchored findings using
the format defined in `consolidation.md`. Do not emit severity sections. A self-review with no
blocking findings must state the verdict (`PASS` or `WARN`) and end with `Next: run \`crew commit\`
to continue.` A blocked self-review must state `BLOCK` and end with `Next: run \`crew review
address\` to resolve the findings.`

A finding line carries its kind beside its label when one was recorded, and `persist` renders the
confidence line under the verdict — do not write either into the report body yourself:

```
1. [attention] · security **`path/to/file.ts — line N`** — one-line title
```

Both are optional in the sense that a finding without a clear kind omits the suffix rather than
inventing a value. The `· kind` slot is also defined in the code-review template in
`consolidation.md`, which is the shape a finding is actually written in; this file only shows it in
the reply. The confidence line comes from `--confidence` / `--confidence-reason`, and a report that
already carries a `Confidence:` line is refused by `persist`.

## Render the report, do not re-author it

The reply is the persisted `report.md` passed through unchanged, under its `## Review:` heading. Do
not summarize, re-word, or rebuild it from your notes: every finding already carries its `file:line`
anchor, its severity label, and the code snippet `consolidation.md` requires, and a rewrite is how
those snippets get dropped.

A reply that shows findings as prose with inline `` `file:line` `` and no fenced block has failed
this step even when `report.md` on disk is correct. Before sending, check that the reply holds every
fence `report.md` holds and that each `[blocking]` finding shows its anchored snippet.

## Do not write the generated sections

`persist` appends `### Coverage by layer` and `### Files reviewed` itself, from the layer map and
`--files`. Write the report body — heading, findings, verdict, next step — but not those two sections:
a report carrying either as a real heading is rejected rather than merged, so the section cannot
appear twice with the reader unable to tell which copy is authoritative. Quoting a heading inside a
finding, or using a deeper `####` heading, is not a duplicate.
