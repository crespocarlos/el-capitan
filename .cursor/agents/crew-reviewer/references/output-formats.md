# Review output and handoff

Emit `## Review: <mode> — <summary>`, followed by one flat numbered list of anchored findings using
the format defined in `consolidation.md`. Do not emit severity sections. A self-review with no
blocking findings must state the verdict (`PASS` or `WARN`) and end with `Next: run \`crew commit\`
to continue.` A blocked self-review must state `BLOCK` and end with `Next: run \`crew review
address\` to resolve the findings.`

## Render the report, do not re-author it

The reply is the persisted `report.md` passed through unchanged, under its `## Review:` heading. Do
not summarize, re-word, or rebuild it from your notes: every finding already carries its `file:line`
anchor, its severity label, and the code snippet `consolidation.md` requires, and a rewrite is how
those snippets get dropped.

A reply that shows findings as prose with inline `` `file:line` `` and no fenced block has failed
this step even when `report.md` on disk is correct. Before sending, check that the reply holds every
fence `report.md` holds and that each `[blocking]` finding shows its anchored snippet.
