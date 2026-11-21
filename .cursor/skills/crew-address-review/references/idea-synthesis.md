# Idea-mode synthesis

Step 4 for an idea or spec review. The artifact is a plan, not code: nothing in the code the planned
change describes is touched, but a spec review does write its SPEC.md.

1. If the user chose `none`, skip synthesis entirely — go straight to the summary.
2. Collect every accepted and nit item, plus any user answers to Needs Input items.
3. Locate the original artifact:
   - **Spec review** (`## Review: Spec`): the artifact is `<task>/SPEC.md` — read it. A finding citing
     a different path overrides this. Do not ask the user to paste a file already on disk.
   - **Idea review** (`## Review: Idea`): the artifact is the pasted text in the conversation (or the
     output of the prior `crew review idea` turn). If it is not recoverable from context (scrolled
     out or session reset), ask: `"I can't locate the original idea text in context — please paste it
     and I'll produce the revised version."` Then wait.
4. Draft the **revision** in memory, incorporating every accepted change. Do not write it yet: for a
   file target this produces the text to write, for pasted text the text to emit. Match the original
   structure and heading levels; add no sections, and remove nothing unless a finding specifically
   called it out.
5. **Verify the draft** against the accepted set:
   - Each accepted finding is reflected. Use the finding's `Fix:` field as the check when it has one;
     a `[nit]` or answered `[needs more info]` row carries no `Fix:`, so check it against the change
     named in its title clause.
   - **Sibling check:** for every accepted fix targeting a specific pattern (a condition, a field, a
     step, a flow branch), scan the full text for structurally identical instances of that pattern — the
     same kind of condition in another branch, the same field missing in a parallel step, the same gap
     in a sibling flow — and apply the same fix to each. Do not require a separate finding per sibling.
     When the artifact is the file that defines a mode or skill's own rules, the sweep covers those
     rules too, which is the same rule code mode's Step 4 states.
   - The revision introduces no new structural contradiction; fix an obvious one inline.
   - Rejected findings are absent (do not silently re-introduce what was dismissed).
6. Append a `## Decisions` section listing every Rejected or Deferred finding with a one-line reason:
   `- [rejected] <finding title>: <reason>` or `- [deferred] <finding title>: <reason>`. For a file
   target this is a new section in that file; for pasted text it ends the emitted revision. It is a
   prior-decisions log for the next reviewer — never omit it when anything was rejected or deferred.
7. **Self-review pass**, still before writing, using the same adversarial and product-flow lenses
   (internal reasoning only, no subagent dispatch, no tool calls), capped at one pass:
   - *Adversarial*: does the revision introduce a new assumption, gap, or failure mode the original
     did not have?
   - *Product flow*: does an accepted fix break a user journey, or leave a new empty or error state
     unaddressed?

   If a new `[blocking]` or `[concern]` turns up, fix it in the draft and note `(self-review: fixed
   inline)` in the summary. If a new `[needs more info]` needs user input, ask now, before the write —
   nothing is on disk yet, so the answer shapes one write rather than requiring a revert.
8. **Write or emit the verified revision.** For a file target, write the draft in one pass, log each
   landing with Step 3b `--outcome fixed`, and show a diff of the changed sections rather than pasting
   the whole file. For pasted text, emit it inline under `## Revised Idea`.
