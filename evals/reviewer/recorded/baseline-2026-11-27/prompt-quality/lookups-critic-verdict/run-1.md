Assessment: request-changes — the lookups fallback rule puts a note at the end of the reply, which collides with the critic contract's last-line Verdict rule and would make a correct run look incomplete.

1. [blocking · 4] **`.cursor/agents/references/lookups.md:19`** — the fallback note goes at the end and collides with the Verdict-last rule
```
say so in one line of your output: `code search unreachable: used text search`. Your own file says
where that line goes; without such a place, put it at the end.
```
`critic-contract.md` sets output, and it says "a reply whose last line is not the Verdict line is treated as incomplete, not as approval." The contract gives no place for the note, and the critics' own files are not shown to give one either. So the default "put it at the end" applies and pushes the Verdict line out of last position. The specwriter then reads a valid review as incomplete. The `unverified (docs server unreachable)` marker has no stated place in the output either.
Fix: in `critic-contract.md` Output, say the note and the unverified markers go in a line before the findings, or in the finding they affect, and that the Verdict line stays last. Alternatively change the default in `lookups.md` to "before your findings" and leave the end to the outcome line.

2. [attention · 3] **`.cursor/agents/references/critic-contract.md:10`** — codebase verification conflicts with the docs-only rule for product facts
```
Verify the spec's claims against the codebase, and flag a claim you could not verify instead of
assuming it.
```
The new pointer is directly above this line. `lookups.md` says to leave an unreachable-docs claim unsettled "rather than deciding it from code or memory". A spec's claims about product or API behaviour are claims about both. A critic cannot tell whether code evidence settles them or whether only docs do. The contract also lacks a verdict-level instruction for `unverified`. For example, it does not say whether an unverified claim counts as a finding or toward the 5-finding cap.
Fix: narrow the sentence to "Verify the spec's claims about this repository's code against the codebase; product and API claims follow lookups.md." Then say how an `unverified` claim is reported.

3. [needs more info · 2] **`.cursor/agents/references/critic-contract.md:8`** — the pointer path may not resolve for the critic
`~/.cursor/agents/references/lookups.md` is a home-directory path, but the file is added at the repo-relative `.cursor/agents/references/lookups.md`. `lookups.md` also depends on `~/.agent/config.json`. If a critic cannot read the file at that path, it silently skips the lookup rules, because a missing reference raises no error. Does the specwriter install or resolve `~/.cursor/...` the way it does for this contract file, which it "appends" and does not point to? If not, a critic gets only the pointer line and none of the lookup guidance. Inlining the file or having the specwriter append it would avoid that.