Assessment: request-changes — the test pins exact prose, including a hard-wrapped line break, rather than the rule, and the `deliver now` check is not tied to the rule.

Read beyond the package: none. A grep of the working directory found no `.md` files, so I could not check that either pinned string exists in the orchestrator files.

1. [attention · 4] **`evals/tools/test_lint_rules.py:12`** — Test pins prose verbatim, including a line wrap
```python
(".cursor/agents/crew-specwriter.md", "A critic that returns no reply gets one\n   resume, never a second dispatch"))
```
The needle contains a newline and three spaces of indentation, so it matches only the file's current hard-wrap and list indentation. Re-wrapping the paragraph, changing its indentation, or rewording it without changing the rule fails the test. The rule is unchanged in those cases. Conversely, the sentence can stay in place while the surrounding text contradicts it, and the test still passes. The test checks the wording, not the behaviour the rule exists for.
Fix: Normalise whitespace before matching (`" ".join(text.split())`) and match a short, stable phrase. Ideally, check for structure such as a `deliver now` instruction under a named resume section.

2. [attention · 4] **`evals/tools/test_lint_rules.py:18`** — The `deliver now` check is independent of the rule
```python
assert rule in text and "`deliver now: " in text, path
```
The second condition passes if the string appears anywhere in the file. A file that says "resumed once, never re-dispatched" but resumes with a different message passes as long as `deliver now: ` appears in an unrelated place. Another bad implementation that passes is one where the resume sentence exists but the "once" limit is removed from the body. The test also shows only what the check accepts, with no case that it rejects.
Fix: Require both phrases within the same paragraph or section. Alternatively, include `deliver now` in each row's needle so it is tied to that rule.

3. [nit · 3] **`evals/tools/test_lint_rules.py:10`** — The crew-reviewer rule is checked only through dispatch.md
The docstring and the change description say crew-reviewer carries the rule, but the row checks only `references/dispatch.md`. If `crew-reviewer.md` stops referencing `dispatch.md`, the test still passes while the rule no longer applies to it. The cost is a false assurance for one of the two orchestrators.
Fix: Add a row for `crew-reviewer.md`, or assert that it references `dispatch.md`.

4. [nit · 2] **`evals/tools/test_lint_rules.py:10`** — Test is appended to the handoff lint test file
`test_lint_rules.py` holds `test_handoff` for lint rules. The new test reads agent prose and has nothing to do with the lint. The cost is that a failure here looks like a lint regression, and the rows and constant are far from where the agent files are maintained.
Fix: Move it to a test module for agent files, if one exists, or name the reason it belongs here.