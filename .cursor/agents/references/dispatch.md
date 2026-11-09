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

A persona with no findings ends its response with the line `### Verdict: no findings`.

A persona that judges the artifact outside its lane (no prompt files, no user-facing surface) emits
the same line plus one sentence of reason. It does not end with a bare statement of disinterest,
because the orchestrator treats a response with neither a finding nor this verdict line as
incomplete and relaunches it.

A persona may not treat an unverified absence or a claim that depends on blocked reads as a grounded
finding; mark it `[needs more info]` and name the blocked read. The orchestrator remains responsible
for verifying findings against the authoritative repository before consolidation.
