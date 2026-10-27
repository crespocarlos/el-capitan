# Review output and handoff

Emit `## Review: <mode> — <summary>`, followed by one flat numbered list of
anchored findings using the format defined in `consolidation.md`. Do not emit
severity sections. A self-review with no blocking findings must state the
verdict (`PASS` or `WARN`) and end with `Next: run \`crew commit\` to
continue.` A blocked self-review must state `BLOCK` and end with
`Next: run \`crew review address\` to resolve the findings.`
