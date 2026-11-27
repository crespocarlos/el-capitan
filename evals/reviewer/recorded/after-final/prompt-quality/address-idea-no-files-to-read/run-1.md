Assessment: request-changes — the edit leaves unreconciled contradictions: Step 2 still says "No files to read", and Step 4 has two overlapping "Idea mode" blocks.

Read beyond the package: `.cursor/skills/crew-address-review/SKILL.md` (full Steps 1–4 as they stand after the change)

1. [blocking · 5] **`.cursor/skills/crew-address-review/SKILL.md:48`** — Step 2 still says "No files to read", but Step 4 now reads the spec file
```
**Idea mode:** No files to read. For each finding:
```
Step 4 step 3 says "read that file. Do not ask the user to paste what is already on disk." Step 2 says idea mode reads no files. A reader that follows Step 2 literally evaluates the findings without the spec. It can then accept a finding the spec already addresses, or reject one the spec's text would have shown to be valid. Step 2 is untouched by the diff, so the rule is stale and the change introduced the conflict.
Fix: Reword to "No code files to read. When the artifact is a spec file, read it before assessing, so you judge each critique against the file's current text. For pasted text, use the conversation."

2. [blocking · 4] **`.cursor/skills/crew-address-review/SKILL.md:75`** — Step 4 has two "Idea mode" blocks that overlap and cite a nonexistent rule
```
**Idea mode with a file target:** the same edit rules apply — ...
Idea mode's "synthesis, not implementation" rule
means it does not touch code the spec describes; it does write the spec.

**Idea mode:** synthesis, not implementation. The artifact is usually pasted text, but a spec review
targets a `SPEC.md` file; in that case the "revised idea" is an edit to that file, not a chat reply.
```
The first block quotes a "synthesis, not implementation" rule that is defined only afterwards in the second block. The second block repeats the file-target rule, and it still calls the output a "revised idea". Steps 3–5 then say it again. The file-target behaviour is stated three times, so the copies will drift. A reader hitting the first block cannot tell whether "Idea mode" (no label) applies to file targets or only to pasted text.
Fix: Keep one block. For example: "**Idea mode:** synthesis, not implementation. Never edit code the spec describes. For a file target, read the file immediately before editing and apply the revision to it (steps below). For pasted text, emit the revision as text." Delete the duplicate sentences.

3. [attention · 4] **`.cursor/skills/crew-address-review/SKILL.md:78`** — The file-target trigger is ambiguous and has no handling for failure
```
**Spec review, or any review whose target is a file** (the `## Review:` heading names it, or the
findings cite `SPEC.md`): read that file.
```
"Findings cite `SPEC.md`" is a loose trigger. A pasted idea review might mention `SPEC.md` in passing, and the file may be missing, renamed, or at another path. No branch covers an unreadable file or a path the findings do not name. The agent might then edit the wrong file, or silently fall back to chat text. The mode-selection lines (15 and 29) also use "idea"/"spec" in the heading, while this trigger uses the heading naming a file. That is a second criterion.
Fix: Define it once: "the file path named in the `## Review:` heading or in the findings' anchors. If it is absent or unreadable, ask the user for the path; do not guess." Tie it to the Step 1 mode test.

4. [attention · 3] **`.cursor/skills/crew-address-review/SKILL.md:15`** — The 3-turn budget and the "Never apply any change" line do not account for file edits
```
synthesize the revision if approved. The revision is an edit to the spec file when the artifact is one ... 3 turns.
```
Idea mode did not edit anything before. Now it makes real edits to a file, but nothing says how edits are logged. Code mode logs "each outcome", and the file-target path only says to "show the changed sections as a diff". A partly failed edit, such as a heading mismatch, has no reporting rule. Nothing in the package, such as an eval or regression row, covers the new file-edit path.
Fix: Say "log each edit outcome as in code mode". Add a check or eval case for a spec review that ends with the file edited and no pasted full text.