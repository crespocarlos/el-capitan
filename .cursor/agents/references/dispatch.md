# Shared dispatch instructions

Run orchestrators inline. Dispatch personas only from the main session: use Cursor Task or Claude
Agent, preserve inherited model selection, and use the documented fallback only when native dispatch
is unavailable.

Reviewer personas may run read-only: Cursor Ask mode, or a Claude Code read-only subagent, where
repository reads and artifact writes are unavailable, and the `claude -p` fallback likewise returns
only stdout. Dispatch prompts must embed the immutable evidence (a path to a diff file is not
evidence) needed for the assigned lens: diff, contract, relevant file excerpts, and explorer
findings. Never rely on a persona writing its own artifact.

**PR mode:** the package is the only repository evidence a persona may use. Every code excerpt must
identify `path:line@headSHA7` and come from `gh api` at that head. A persona must not use the local
checkout — no file reads, repository search, semantic search, or Explorer output, whatever the
harness names those tools — to verify a PR claim. It may return `[needs more info]` only when it
names the missing PR-head path or excerpt.

One exception, and it belongs to the orchestrator rather than the persona: `crew-reviewer` may run
`agent-context.py` to collect repository guidance (`AGENTS.md`, `CLAUDE.md`) and place the result in
the package. Guidance describes the reviewer's own conventions rather than the change, so it is
legitimate context. It also comes from the local checkout, not the PR head, and therefore is **not
PR-head evidence**: when the PR itself changes a guidance file, treat the collected text as
approximate and cite a head excerpt for any conclusion that depends on the rule being added. A
persona reads guidance from its package, never the working tree, so the evidence trail in
`<persona>.in.md` stays complete.

**The reply text is the only thing the orchestrator receives.** A persona that writes findings into a
file, a scratch artifact, or a summary block ("findings delivered above", "see next") hands back
nothing, and the orchestrator must treat that run as incomplete and relaunch it. Every dispatch
prompt therefore states this and requires a flat numbered list of findings, each beginning with its
severity label and carrying a `path:line` anchor. A conversational summary is never a zero-findings
verdict; only the `### Verdict: no findings` line is.

When the package has a hunk index, each `[blocking]` and `[attention]` finding also names the hunk
ids that cause it after its anchor (`src/a.ts:42 (h7)`). A Reading map orders those ids; without
one, the package still supplies a compact hunk-to-file reference.

The compact reference comes from `hunks.index.md` (ids, files, line ranges, size flags), never from
`hunks.md`, whose per-hunk bodies re-quote a diff the package already carries. `hunks.md` is for the
layer-mapping pass, which sees the index only and no diff. The dispatch prompt states this.

A persona with no findings ends its response with the line `### Verdict: no findings`.

A persona that judges the artifact outside its lane (no prompt files, no user-facing surface) emits
the same line plus one sentence of reason. It does not end with a bare statement of disinterest,
because the orchestrator treats a response with neither a finding nor this verdict line as
incomplete and relaunches it.

A persona may not treat an unverified absence or a claim that depends on blocked reads as a grounded
finding; mark it `[needs more info]` and name the blocked read. The orchestrator remains responsible
for verifying findings against the authoritative repository before consolidation.
