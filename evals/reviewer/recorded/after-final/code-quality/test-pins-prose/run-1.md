Assessment: request-changes — the test pins exact prose, including a hard-wrapped line break, and does not check that crew-reviewer reaches the rule it claims to cover.

Read beyond the package: grep of the working directory. It matched only the test file. The `.md` files sit under hidden `.cursor/`, which the search skips by default, so I could not confirm the rule text exists.

1. [attention · 4] **`evals/tools/test_lint_rules.py:12`** — the pinned phrase embeds a hard-wrap and indentation
```
"A critic that returns no reply gets one\n   resume, never a second dispatch"
```
The test pins prose beyond the contract. Rewrapping the paragraph in `crew-specwriter.md`, or changing the indent from 3 spaces to 2, fails the test although the rule is unchanged. Rewording "gets one resume" to "is resumed once" fails it too. Meanwhile, a file that keeps the sentence but contradicts it elsewhere still passes.
Fix: Normalize whitespace before matching, for example `" ".join(text.split())`, and pin only a short stable token. If the rule needs a stronger guard, have a lint check parse a marker line instead of matching a full sentence.

2. [attention · 4] **`evals/tools/test_lint_rules.py:19`** — the `deliver now` check is not tied to the rule, and crew-reviewer is never checked
```
assert rule in text and "`deliver now: " in text, path
```
A file where the rule sentence says "resume" but the `deliver now` backtick string appears in an unrelated place passes. A file where only the `deliver now` half is broken reports the same bare `path` message, so you can't tell which half failed. The docstring and the first row say crew-reviewer is covered "through dispatch.md". Nothing checks that `crew-reviewer.md` references `dispatch.md`, so removing that reference leaves the test green and the rule dead for crew-reviewer. This is the weakest point of the test, since a green run doesn't show that each orchestrator carries the rule.
Fix: Put the `deliver now` text in the pinned phrase for each row, or assert the two parts separately with distinct messages. Add a row or assertion that `crew-reviewer.md` mentions `dispatch.md`.

3. [nit · 3] **`evals/tools/test_lint_rules.py:10`** — the rows and the test sit above `test_handoff` in a file named for lint rules
This test checks the content of agent prompt files, not lint behaviour, and it is unrelated to the neighbouring `HANDOFFS` table. Cost: a reader looking for lint-rule coverage will not expect it here, and the prompt text it reads belongs to prompt-quality's lane.
Fix: Confirm that no existing test already checks orchestrator-file content. If one exists, move this row there.