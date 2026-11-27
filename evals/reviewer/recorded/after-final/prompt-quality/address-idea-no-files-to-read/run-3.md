Assessment: request-changes — Step 2 still tells idea mode to read no files, and Step 4 now says to read the spec file, so the skill contradicts itself.
Read beyond the package: none (the package holds only this SKILL.md)

1. [blocking · 5] **`.cursor/skills/crew-address-review/SKILL.md:48`** — Step 2 still says idea mode reads no files, but Step 4 reads the spec
```
**Idea mode:** No files to read. For each finding:
```
Step 4 now says "read the file immediately before editing" and "read that file". A literal reader of Step 2 treats "No files to read" as a ban on reading. It may refuse the read, or ask the user to paste `SPEC.md`, which Step 4 forbids. Line 34 adds "do not read any file", which is about locating findings but can be read the same way. This change introduced the conflict.
Fix: change Step 2 to "No code files to read; the spec file is read in Step 4 when the target is a file." Scope line 34's "do not read any file" to the findings source.

2. [blocking · 4] **`.cursor/skills/crew-address-review/SKILL.md:71`** — Step 4 has two overlapping "Idea mode" blocks with different contracts
```
**Idea mode with a file target:** the same edit rules apply — read the file immediately before
...
**Idea mode:** synthesis, not implementation. ... the "revised idea" is an edit to that file, not a chat reply.
```
The file-target rule is stated three times: lines 71-73, lines 75-76, and the numbered steps 3-5. The general "Idea mode" block says "usually pasted text", while step 4 says "revised idea" for a file. Step 3 sub-bullet one says "read that file" and the block above it says "read the file immediately before editing". It is unclear whether the read happens once or twice. The sentence "the same edit rules apply" points at code mode's "log each outcome", which conflicts with "show the changed sections as a diff". These copies will drift apart.
Fix: delete lines 71-76 and keep one rule in steps 3-5. Add a single sentence saying the file is read immediately before the edit.

3. [attention · 4] **`.cursor/skills/crew-address-review/SKILL.md:20`** — The "Never mix modes" rule is contradicted by file edits in idea mode
```
Never mix modes. If the review heading contains "Idea" or "Spec" (case-insensitive), use idea mode
throughout.
```
Idea mode now applies "the same edit rules" as code mode, so it does mix modes. Line 12-13 also defines code mode as "apply edits", which now describes idea mode too. A reader cannot tell which rule wins when the two collide, for example whether idea mode needs the silent file-check.
Fix: state which code-mode edit rules idea mode borrows, and drop "the same edit rules apply".

4. [attention · 3] **`.cursor/skills/crew-address-review/SKILL.md:81`** — The file-target trigger is vague
```
(the `## Review:` heading names it, or the findings cite `SPEC.md`)
```
"any review whose target is a file" is hard to recognise, and it is pinned to the literal name `SPEC.md`. A spec at another path, or an idea review that cites `SPEC.md` only as a reference, is misclassified. That can overwrite a file that was never the artifact. Nothing covers a missing or unreadable file, or a file that has changed since the review.
Fix: define the target as the file path in the review's header or its scope line. Add a fallback: if the file is missing or unreadable, ask the user. Don't edit a file that is only cited.

5. [attention · 3] **`.cursor/skills/crew-address-review/SKILL.md:89`** — The "no new sections" and "match heading levels" rules were written for chat text and are unchanged for in-place edits
```
Do not add new sections; do not remove content unless a finding specifically called it out.
```
A finding such as "spec lacks an acceptance criterion" may need a new section in a real file, and the rule blocks it. No eval or check covers the new file-edit path, and nothing says which regression would catch a wrong overwrite.
Fix: allow additions that an accepted finding requires. Add an eval case for a spec review that targets `SPEC.md`.