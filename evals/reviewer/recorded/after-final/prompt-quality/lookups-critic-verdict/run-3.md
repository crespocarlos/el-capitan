Assessment: request-changes — the shared lookups reference collides with the critic contract's output rules. The two cannot both be followed on the fallback path, and no check covers the change.

Read beyond the package: `.cursor/agents/references/critic-contract.md` (full), a grep of the working directory for the lookups terms.

1. [blocking · 4] **`.cursor/agents/references/lookups.md:16`** — the fallback note has no valid place in a critic reply

```
say so in one line of your output: `code search unreachable: used text search`. Your own file says
where that line goes; without such a place, put it at the end.
```

The critic contract says "a reply whose last line is not the Verdict line is treated as incomplete, not as approval." The critic contract defines no place for a note. Its output section lists only severity groups and the Verdict line. A critic whose code index is down follows lookups.md and puts the note at the end. The reply then does not end with `Verdict: N finding(s)`, and the specwriter marks it incomplete and relaunches it. The critic's own file might name a place, but the contract is the file that sets output, and it does not.

Fix: in critic-contract.md, state where lookup notes go, for example "put the lookup note on the line before the `Verdict:` line; the Verdict line stays last". Or change lookups.md to "never after a required closing line".

2. [attention · 4] **`.cursor/agents/references/lookups.md:27`** — the `unverified` marker has no slot in the critic's severity-grouped output, and it conflicts with the 5-finding cap

```
mark the claim
`unverified (docs server unreachable)` and leave it unsettled rather than deciding it from code or
memory.
```

The critic contract says "flag a claim you could not verify instead of assuming it" and caps output at 5 findings grouped by severity. The lookups file does not say whether an unverified claim counts as a finding, which level it takes, or whether it can be dropped when the cap is full. When the docs server is down, a critic can bury the markers or drop them to stay under the cap. The specwriter then reads the spec as checked.

Fix: add one line to the critic contract: an unverified claim is a finding at **Consider** or higher and counts toward the cap.

3. [attention · 3] **`.cursor/agents/references/lookups.md:22`** — the mandatory docs lookup collides with the critic's budget and tools

```
is checked on the docs server and cited
by URL. Search the docs (`search_internal_docs`), then fetch the page you cite.
```

The opening says "Your own file still sets your budget, your tools". Critics also have a finding cap and, probably, a tool budget. Every spec claim about product or API behaviour now costs two docs calls. The text does not say which rule wins when the budget runs out mid-check. The reader will either overrun the budget or stop silently. It also names the harness tool `search_internal_docs` where the capability would do.

Fix: state the precedence, for example "if the budget runs out, mark the remaining claims `unverified (budget)`", and say "the docs search tool" instead of naming it.

4. [attention · 3] **`.cursor/agents/references/critic-contract.md:8`** — the pointer's path may not resolve, and the lookup rules now live in two places

```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```

The files sit in the repo's `.cursor/agents/references/`, but the pointer uses `~/.cursor/...`. The contract is appended to the dispatch prompt, and a critic that reads the path literally may not find the file at home. The pointer also carries its own partial trigger, "code you cannot locate or a product or API fact", which repeats lookups.md's section scopes and will drift from them. The lookups guidance is also not tied to the prior line, "Verify the spec's claims against the codebase", which would let a critic settle product claims from code.

Fix: use the same path form as other references (confirm it resolves for critics), and shorten the pointer to "Lookups: follow `…/lookups.md`." Say that product and API claims are verified on the docs server and not from code.

5. [needs more info · 2] **`.cursor/agents/references/lookups.md:7`** — the server names depend on a config file the reader may not see

`The servers are the ones named in ~/.agent/config.json mcp: code_search ... docs`. If a critic cannot read that config, it cannot tell whether the servers are absent or merely unreadable, and it takes the fallback path either way. Is `~/.agent/config.json` readable by dispatched critics, and does a critic's `tools:` list expose the same server names? If not, the fallback fires every time and critics always report "unreachable".

6. [needs more info · 2] **`.cursor/agents/references/critic-contract.md:8`** — nothing measures the change

The change adds a mandatory docs lookup and a fallback note to every critic dispatch, and the contract's Verdict line is a parsed format. The package contains no eval case or check for a critic that runs with the code or docs server down. Which regression row would catch finding 1, where a reply whose last line is the fallback note and not the Verdict line is relaunched?