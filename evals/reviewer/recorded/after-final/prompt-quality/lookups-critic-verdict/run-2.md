Assessment: request-changes — the critic contract now loads a lookups file whose fallback line ("put it at the end") collides with the contract's rule that the reply must end with the Verdict line.

Read beyond the package: `.cursor/agents/references/critic-contract.md` (full file). Grep for lookup terms across the working directory found only `lookups.md`.

1. [blocking · 5] **`.cursor/agents/references/lookups.md:18`** — fallback note placement contradicts the critic contract's last-line rule
```
`code search unreachable: used text search`. Your own file says
where that line goes; without such a place, put it at the end.
```
Contract: "a reply whose last line is not the Verdict line is treated as incomplete, not as approval."
The critic contract defines no place for the note, so the lookups rule applies and the note goes at the end. A critic whose code index fails writes the note after `Verdict: N finding(s)`. The specwriter then reads the reply as incomplete and relaunches it or discards it. This hits exactly the runs where the index was down.
Fix: add a line to `critic-contract.md` Output saying where the note goes, for example "put lookup notes before the Verdict line, which stays last." Or change the lookups default to "before your outcome line, if your output has one."

2. [attention · 4] **`.cursor/agents/references/lookups.md:28`** — the unverified-claim marker conflicts with the contract's output shape
```
mark the claim
`unverified (docs server unreachable)` and leave it unsettled
```
Contract: "At most 5 findings across all levels."
The contract says to flag an unverifiable claim. The lookups file says to mark it and leave it unsettled, but it doesn't say whether the mark is a finding, which severity it takes, or whether it counts toward the cap of 5. A critic with several unverifiable claims either exceeds the cap or drops marks silently. Neither file says which wins.
Fix: in `critic-contract.md`, state that an `unverified` mark is a finding at **Consider**, or a line outside the cap.

3. [attention · 4] **`.cursor/agents/references/lookups.md:4`** — the opening sentence assumes a budget and an output slot the critic contract does not define
```
Your own file still
sets your budget, your tools and where a note goes in your output
```
The critic contract says it "sets evidence, budget and output", and the critic's own file "sets its lens". Lookups defers budget and note placement to "your own file", which for a critic is that lens file, and the contract takes over those same things. The reader cannot tell which file owns the budget or the note slot. Resolving finding 1 also removes this ambiguity.
Fix: reword it as "the file that loaded you sets…", or have the contract name the owner explicitly.

4. [attention · 3] **`.cursor/agents/references/lookups.md:24`** — the mandatory docs check meets a "5 findings" budget and a codebase-only evidence rule
```
is checked on the docs server and cited
by URL. ... Never settle such a claim from memory
```
Contract: "Verify the spec's claims against the codebase".
The contract's Evidence section says to verify against the codebase. Lookups says every product or API claim must be checked on the docs server, with a search and a fetch. With a tight critic budget, a spec with many API claims either uses up the budget on docs fetches or skips the rule. The pointer line does not say docs verification overrides the codebase check, or what to do when the two disagree.
Fix: state the precedence in the contract, for example "docs server for product and API behaviour, the codebase for the spec's own code claims".

5. [attention · 3] **`.cursor/agents/references/lookups.md:7`** — a tool-name and config-path dependency the reader may not resolve
```
The servers are the ones named in `~/.agent/config.json` `mcp`: `code_search` for the code index,
`docs` for the docs server.
```
A critic dispatched by the specwriter may not be able to read `~/.agent/config.json`. It also gets only the name `search_internal_docs`, with no `code_search` tool name. It would then guess a tool name or fall back silently. This is a harness tool required by name, where the capability alone would do.
Fix: describe the capabilities ("the code-index search tool", "the docs search and fetch tools") and drop the config path.

6. [needs more info · 2] **`.cursor/agents/references/critic-contract.md:8`** — nothing measures the change
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The change alters critic outputs. A fallback note could now push the Verdict line off the last position, and the specwriter parses that line. Is there an eval case or check for a critic run with the code index unreachable? If none exists, a regression of this kind would go unnoticed.