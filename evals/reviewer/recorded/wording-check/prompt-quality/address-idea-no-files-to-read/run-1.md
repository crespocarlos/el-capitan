Assessment: request-changes — the new file-edit path conflicts with the unchanged "No files to read" line and is described in two overlapping blocks.

Read beyond the package: `.cursor/skills/crew-address-review/SKILL.md` (grep of the idea-mode references)

1. [blocking · 4] **`.cursor/skills/crew-address-review/SKILL.md:48`** — Unchanged "No files to read" contradicts the new file-target rule
```
**Idea mode:** No files to read. For each finding:
```
The diff leaves this line alone. The edited sections now say to read `SPEC.md` and edit it. A literal reader on a spec review reaches the evaluation step first and is told there are no files. It may then skip the read and rely on conversation context. It may also treat the later read as a violation. In both cases the spec is edited from stale or missing content.
Fix: Change the line to "**Idea mode:** Evaluate findings inline; do not read files during evaluation. For each finding:". Make the file read happen only in the synthesis step.

2. [attention · 4] **`SKILL.md:71-76`** — Two overlapping "Idea mode" blocks in one section
```
**Idea mode with a file target:** the same edit rules apply …
**Idea mode:** synthesis, not implementation. The artifact is usually pasted text, but a spec review
targets a `SPEC.md` file; in that case the "revised idea" is an edit to that file, not a chat reply.
```
The file-target rule appears three times: in this block, in the generic block that follows it, and in steps 3–5. The generic "**Idea mode:**" label also matches a file-target review. The reader cannot tell which block governs. The phrase "the same edit rules apply" points at code-mode text that is never defined as a rule set. The "not touch code" sentence is also awkward: it quotes a "synthesis, not implementation" rule that only appears one paragraph later.
Fix: Delete the "Idea mode with a file target" block and the second sentence of the generic block. Keep steps 3–5 as the single owner. Add "read the file immediately before editing" to step 4.

3. [attention · 3] **`SKILL.md:80-83`** — The file-target trigger is vague and its fallback is missing
```
(the `## Review:` heading names it, or the findings cite `SPEC.md`)
```
"Any review whose target is a file" is recognised only through a heading that may not name a path, or through findings that cite `SPEC.md`. The wording hardcodes one filename. A spec at another path is missed, so the agent falls into the pasted-text branch and asks the user to paste. There is also no handling for a file that is missing, or for one that has changed since the review ran. An idea review that happens to cite `SPEC.md` is also treated as a file target.
Fix: Say "the review names a file path (for example `SPEC.md`)". If the file cannot be read, fall back to emitting text and say so.

4. [attention · 3] **`SKILL.md:15-18, 90-93`** — The 3-turn budget and the diff output are unmeasured
```
approved. The revision is an edit to the spec file when the artifact is one, and emitted text when
```
Step 5 asks for a diff of the changed sections plus the path. The agent has to produce that diff without git or a stated tool. No eval case or check covers the new file-edit branch, so a regression to chat-only output would not be caught. The 3-turn budget is also unchanged even though the work now includes reading, editing and showing a diff.
Fix: Say how to show the diff (before/after excerpts). Add a case where a spec review edits `SPEC.md` and a case with pasted text.