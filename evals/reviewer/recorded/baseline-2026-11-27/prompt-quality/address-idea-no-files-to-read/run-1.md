Assessment: request-changes — the new file-edit path conflicts with an unchanged "No files to read" rule in the same skill and with the "Never mix modes" rule. The edit also has no sequencing against the approval gate.

1. [blocking · 5] **`.cursor/skills/crew-address-review/SKILL.md:48`** — Unchanged "No files to read" contradicts the new file-target flow
```
**Idea mode:** No files to read. For each finding:
```
The diff adds "Idea mode with a file target … read the file immediately before editing". Step 3 also says "read that file". Line 48 still tells the model to read no files while it evaluates findings. A model following line 48 may skip reading `SPEC.md` during evaluation, then read it only at synthesis. Or it may treat the two rules as a conflict and fall back to chat text. This is the same mode, and the later rule silently overrides the earlier one.
Fix: Reword line 48 to "No code files to read (a spec file is read only at synthesis, see below). For each finding:". This is a defect in the diff, because the diff adds the contradicting rule without updating line 48.

2. [attention · 4] **`.cursor/skills/crew-address-review/SKILL.md:71`** — The file-target rule is stated twice, with the heading label duplicated
```
**Idea mode with a file target:** the same edit rules apply — read the file immediately before
…
**Idea mode:** synthesis, not implementation. The artifact is usually pasted text, but a spec review
targets a `SPEC.md` file; in that case the "revised idea" is an edit to that file, not a chat reply.
```
The file-versus-text split is stated in the intro bullet, in the two paragraphs above, in step 3, in step 4 and in step 5. The model gets three descriptions of one rule. The two paragraphs also give "Idea mode" two bold headings, and the second one still says "revised idea". Step 4 renamed that artifact "revision".
Fix: Keep one owner, the "Idea mode with a file target" paragraph. Cut the redundant sentence in the second paragraph and use "revision" throughout.

3. [attention · 3] **`.cursor/skills/crew-address-review/SKILL.md:71`** — "The same edit rules apply" points at rules the code-mode paragraph doesn't hold
```
the same edit rules apply — read the file immediately before
editing, and apply the revision as real edits to it.
```
The only code-mode rule is "read each file immediately before editing it … and log each outcome". "Same edit rules" is ambiguous about whether per-edit outcome logging applies. It is also ambiguous about whether the edits happen before or after the user approves the acceptance table. Step 1 says `none` skips synthesis, but nothing states that the file is written only after approval. A spec on disk is a durable artifact.
Fix: Say explicitly that edits are written only after the user has approved rows in the acceptance table. Say whether outcomes are logged per edit.

4. [nit · 3] **`.cursor/skills/crew-address-review/SKILL.md:20`** — "Never mix modes" now sits awkwardly with a hybrid
```
Never mix modes. If the review heading contains "Idea" or "Spec"
```
Idea mode now performs code-mode-style file edits. The text doesn't say that this is still idea mode, so a model may read it as mixing. The cost is a possible hesitation or fallback to chat text. This is mild because the new paragraph says "the same edit rules apply".
Fix: Add a clause that a file target does not change the mode.