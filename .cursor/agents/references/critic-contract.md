# Spec critic contract

`crew-specwriter` appends this file to the dispatch prompt of each spec critic (`specwriter-scope`,
`specwriter-adversarial`). The critic's own file sets its lens, severity definitions and finding
reference; this file sets evidence, budget and output, and wins where the two disagree about them.

## Evidence

Lookups: follow `~/.cursor/agents/references/lookups.md` before you search for code whose file you do not already know, or rely on a product or API fact.
A lookup note it asks for goes on its own line directly before the `Verdict:` line.

Verify the spec's claims against evidence, and flag a claim you could not verify instead of assuming
it; before an absence claim (no guard, no criterion, no such function), search and read where it
would be first. Your tools read the codebase, not issue trackers, so a link to the originating issue
is evidence you cannot open: judge from what the spec says, and list "originating issue" as
unverified when the answer turns on it.

## One owner per shared concern

Both critics read the same spec, so each shared concern has one owner and the other critic skips it:

- **specwriter-adversarial** owns whether the approach and the criteria prove the goal: a wrong
  premise, a missing criterion, regression, compatibility and security risk, edge cases.
- **specwriter-scope** owns whether the builder can carry it out and check it: task size and order,
  how each criterion and task is verified, the `## Tests` section and its layers, scope creep, and
  any split into smaller specs.

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

<explanation: 2 sentences max — the failure scenario, or for Consider its cost>

<fix: 1 sentence>
```

**The reference is where the fix lands:** name the criterion, task or section whose text must
change, and quote it. The specwriter edits what the reference names, so a reference to a sentence
that only motivates the flaw leaves the text that carries it unchanged.

**The failure scenario** of a Critical or Important finding names, in words, a concrete input or
sequence and the wrong outcome the spec as written produces (inputs → wrong outcome); a quoted name
alone does not say what goes wrong. When you cannot state one, the fix is the question to put under
`## Open questions`. A Consider finding asks for no change, so it states its cost instead.

Zero findings is a valid outcome. **At most 5 findings across all levels**: surface only what would
cause a real implementation problem, and never append one-liners for the findings you cut.

**End with one outcome line.** `Verdict: N finding(s)` after the findings, and `Verdict: 0
finding(s)` for a clean pass, so one shape covers both. The specwriter cannot tell a budget stop
from a clean pass, so a reply without the line is treated as incomplete, not as approval. Under the
turn budget the line reads `Verdict: N finding(s), M unverified` and the names follow it.
