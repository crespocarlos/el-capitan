# Challenging a thread

`crew-pr-resolver` Step 4 asks these of every thread, against the reads already made and with no new
read, before any verdict.

Answer four questions in this order, citing the `path:line` behind each; the last three are the ones
`.cursor/agents/crew-reviewer/references/consolidation.md` asks of a review finding.

1. **Is this a fault or a decision?** A fault is code misbehaving against an intent nobody disputes,
   and the code settles it. A decision is an intent the author chose that the comment asks to change
   — behavior, an API surface, a documented contract, a test's expected value, naming, a data shape.
   The author owns it, so it is **Decide**, never **Apply**, however small the edit. Most threads are
   faults; this reclassifies the minority and is not a veto on ordinary fixes.
2. **Is the premise present?** Does the code the comment describes exist as described, or is the
   comment stale? An absent premise makes the thread **Already Addressed** when the fix landed and
   **Reject** when it never applied — the citation decides which.
3. **Is the chain traceable?** Follow the comment's conclusion through the code. Where the chain
   breaks, the change does not buy the outcome it claims.
4. **Are the stakes real?** Name what concretely breaks on the code in front of you. A cost you
   cannot place on a line is not a reason to change it.

The answers set the thread's confidence in Step 5.
