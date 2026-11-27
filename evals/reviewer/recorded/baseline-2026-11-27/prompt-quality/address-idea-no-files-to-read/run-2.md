Assessment: request-changes — the new file-target path contradicts the unchanged line 48 ("No files to read"), and the added paragraphs overlap each other.

1. [blocking · 5] **`.cursor/skills/crew-address-review/SKILL.md:48`** — Unchanged evaluation step still says idea mode reads no files
```
**Idea mode:** No files to read. For each finding:
```
The diff adds "read that file" in step 3 and "read the file immediately before editing" for file targets. Line 48 sits in the earlier evaluation phase and still tells the model that idea mode has no files to read. For a `SPEC.md` target the two instructions conflict, so the model may evaluate findings without reading the spec, or skip the edit. This is a stale line that the diff should have updated, since it contradicts the new behavior.
Fix: Change line 48 to "**Idea mode:** For a pasted idea there are no files to read; for a file target (e.g. `SPEC.md`), read it first. For each finding:".

2. [attention · 4] **`.cursor/skills/crew-address-review/SKILL.md:71`** — Two overlapping idea-mode headers state the file-target rule twice
```
**Idea mode with a file target:** the same edit rules apply — read the file immediately before
...
**Idea mode:** synthesis, not implementation. The artifact is usually pasted text, but a spec review
targets a `SPEC.md` file; in that case the "revised idea" is an edit to that file, not a chat reply.
```
The file-target rule appears in the first paragraph, in the second paragraph, in step 3, and in step 4, so one rule has four owners. "Read the file immediately before editing" also repeats the read in step 3, which leaves it unclear when the read happens. "The same edit rules apply" points at the code-mode rule without saying which parts carry over. Does the verdict-table and log-each-outcome behavior apply?
Fix: Keep one "Idea mode" block. State "synthesis, not implementation: don't touch code the spec describes" once. Leave the file-versus-pasted split to steps 3–5 only. Say explicitly whether "log each outcome" applies.

3. [nit · 3] **`.cursor/skills/crew-address-review/SKILL.md:93`** — "Revised idea" term is used for a file edit
```
the "revised idea" is an edit to that file, not a chat reply.
```
The diff introduces "revision" as the neutral term but keeps "revised idea" here. One term is used for two things, which is minor, but step 5's "show the changed sections as a diff" gives no format for the path.
Fix: Use "revision" consistently.