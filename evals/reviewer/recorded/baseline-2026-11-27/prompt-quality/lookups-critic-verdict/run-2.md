Assessment: request-changes — the new pointer sends critics to a fallback rule that conflicts with the contract's "last line must be Verdict" rule.

1. [blocking · 4] **`.cursor/agents/references/lookups.md:15`** — fallback note placement collides with the critic's Verdict-last rule
```
say so in one line of your output: `code search unreachable: used text search`. Your own file says
where that line goes; without such a place, put it at the end.
```
The critic contract says "a reply whose last line is not the Verdict line is treated as incomplete, not as approval". It never says where the lookup note goes. A critic that follows the pointer and finds nothing in its own lens file will put the note "at the end", after the Verdict line. The specwriter then discards a finished review as incomplete. The new `Lookups:` line, as the contract's only mention of the note, says nothing about placement. The `lookups.md` intro also says the critic's own file sets where a note goes, while the contract says it sets "evidence, budget and output". Two documents each claim to own placement, and the critic cannot tell which one wins.
Fix: have the contract own the placement: "Put any lookup note (`code search unreachable…`, `unverified (docs server unreachable)`) before the findings or inside the relevant finding, never after the Verdict line." Change the `lookups.md` default to "before your closing outcome line, if your output has one".

2. [attention · 3] **`.cursor/agents/references/critic-contract.md:8`** — the pointer tells critics to leave product claims unsettled, but the contract tells them to verify against the codebase
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
`lookups.md` says to leave a failed lookup "unsettled rather than deciding it from code or memory". The next contract paragraph says "Verify the spec's claims against the codebase". A critic checking a spec's claim about API behaviour gets two instructions that disagree. The contract also doesn't say whether an unverified claim counts toward the "At most 5 findings" cap or what severity it gets.
Fix: add a sentence to the contract: "Product or API claims are verified on the docs server (see lookups). Claims about this repo's own code are verified against the codebase. An unverified claim is flagged as a **Consider** finding and counts toward the cap."

3. [nit · 2] **`.cursor/agents/references/lookups.md:7`** — the two files give config and reference paths under different roots
```
The servers are the ones named in `~/.agent/config.json` `mcp`
```
The contract points at `~/.cursor/agents/references/lookups.md`, while the config lives under `~/.agent/`. If the second root is a typo or a harness-specific path, a critic may fail to find the config. Only the roots differ, so the cost is small. Fix: confirm both paths, or describe the config in capability terms ("the configured code-search and docs servers").