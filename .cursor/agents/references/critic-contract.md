# Spec critic contract

`crew-specwriter` appends this file to the dispatch prompt of each spec critic (`specwriter-scope`,
`specwriter-adversarial`). The critic's own file sets its lens, severity definitions and finding
reference; this file sets evidence, budget and output, and wins where the two disagree about them.

## Evidence

Lookups: follow `~/.cursor/agents/references/lookups.md` before you search for code whose file you do not already know, or rely on a product or API fact.
A lookup note it asks for goes on its own line directly before the `Verdict:` line.

Verify the spec's claims against evidence, and flag a claim you could not verify instead of assuming
it. Your tools read the codebase, not issue trackers, so a link to the originating issue is
evidence you cannot open: judge from what the spec says, and list "originating issue" as unverified
when the answer turns on it.

## Budget

**Your persona file sets the budget** ("stop calling tools at N", its `tool_budget` frontmatter).
The calls go to the spec, then to what you chose to verify; stop at N and write the critique. A long
spec will not fit every read plus the write, so triage before reading anything but the spec, and
name what you left unverified instead of spending the report turn on another read. Claude Code
enforces the turn limit; Cursor does not, so there the discipline is yours. A run that stops on the
limit hands the specwriter nothing, which is worse than a critique that names what it could not check.

## Output

Group findings by severity (**Critical**, **Important**, **Consider**), omitting an empty level. Each
finding uses this shape, with the reference your critic file names:

```
**<reference>** — <one-line summary>

<explanation: 2 sentences max — the problem and why it matters>

<fix: 1 sentence>
```

Zero findings is a valid outcome. **At most 5 findings across all levels**: surface only what would
cause a real implementation problem, and never append one-liners for the findings you cut.

**End with one outcome line.** `Verdict: N finding(s)` after the findings, and `Verdict: 0
finding(s)` for a clean pass, so one shape covers both. The specwriter cannot tell a budget stop
from a clean pass, so a reply without the line is treated as incomplete, not as approval. Under the
turn budget the line reads `Verdict: N finding(s), M unverified` and the names follow it.
