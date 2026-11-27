Assessment: request-changes — Step 2 still says "No files to read" and Step 1 still says "do not read any file", so the new file-edit path conflicts with those rules, and the Step 4 text is duplicated.

Read beyond the package: none (the one read was SKILL.md, the changed file, to see the unchanged Step 1 and Step 2 text)

1. [blocking · 5] **`.cursor/skills/crew-address-review/SKILL.md:48`** — Step 2 still forbids reading files in idea mode
```
**Idea mode:** No files to read. For each finding:
```
Step 4 now tells the agent to read `SPEC.md` and edit it. Step 2 still says "No files to read", and Step 1 says "do not read any file". An agent that follows Step 2 literally evaluates findings without opening the spec. It then cannot tell whether a finding is already addressed or misread, so "Accept"/"Reject" is decided blind. The change did not touch this line, so the file's rules now contradict each other.
Fix: Rewrite Step 2 so it reads the spec file when the target is a file and keeps "No files to read" only for pasted text. Limit the Step 1 "do not read any file" to the findings location.

2. [blocking · 4] **`.cursor/skills/crew-address-review/SKILL.md:71`** — Two "Idea mode" Step 4 blocks overlap, and the second still carries the old behaviour
```
**Idea mode with a file target:** the same edit rules apply — read the file immediately before
...
**Idea mode:** synthesis, not implementation. ... in that case the "revised idea" is an edit to that file, not a chat reply.
```
Both blocks apply to a spec review. The first says "the same edit rules apply", and the second then runs a numbered synthesis flow. The file-target rule is stated three times: here, at line 76, and in item 3/4. The agent has to guess whether the "read immediately before editing" step comes before or after the synthesis steps. It may read the file twice, or skip the pre-edit read because item 3 already read it. The quoted "synthesis, not implementation" rule is also never defined, so the first block's gloss on it is unsupported.
Fix: Merge them into one "Idea mode" block. State the file-versus-pasted split once, in item 3 or 4. Add one line saying the pre-edit read in item 3 satisfies "read immediately before editing", unless an approval turn has passed since the read. Remove lines 71–76.

3. [attention · 4] **`.cursor/skills/crew-address-review/SKILL.md:81`** — The trigger for a file target is vague, and the heading rule ignores it
```
(the `## Review:` heading names it, or the findings cite `SPEC.md`)
```
The mode-detection rule keys off "Idea" or "Spec" in the heading, but a file target is recognised by a different, fuzzy signal. An idea review whose findings mention `SPEC.md` in passing would trigger edits to a file the user never asked to change. A spec review whose findings cite `spec.md` or a different path matches neither condition, so it falls to the paste path and asks the user to paste text. The skill also does not say what to do if the file is missing or empty.
Fix: Define the target as "the path named in the `## Review: Spec` heading or in the review's target line". Say that a file target applies only when that path exists, and otherwise ask. Do not use incidental citations as the trigger.

4. [attention · 3] **`.cursor/skills/crew-address-review/SKILL.md:91`** — "show the changed sections as a diff" has no source and no eval
```
the edit landed in the file; show the changed sections as a diff and name the path.
```
The agent may have no git (the working directory is not a repository) and no diff tool, so it hand-writes a diff that can misstate the edit. Nothing in the change covers the new file-edit path: no eval case or regression row checks that idea mode edits a spec, and none checks that it still emits text for pasted ideas.
Fix: Say "list each changed section with before and after text". Add an eval case for each of the two targets.