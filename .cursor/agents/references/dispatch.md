# Shared dispatch instructions

Run orchestrators inline. Dispatch personas only from the main session: use Cursor Task or Claude Agent, preserve inherited model selection, and use the documented fallback only when native dispatch is unavailable.

Reviewer personas may run in Ask mode, where repository reads and artifact
writes are unavailable. Dispatch prompts must include the immutable evidence
needed for the assigned lens: diff, contract, relevant file excerpts, and
explorer findings. A persona may not treat an unverified absence or a claim
that depends on blocked reads as a grounded finding; mark it
`[needs more info]` and name the blocked read. The orchestrator remains responsible for verifying findings against
the authoritative repository before consolidation.
