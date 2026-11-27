Assessment: request-changes — the change is meant to enforce a resume-once rule in two orchestrator files, but the test only matches prose strings. It would pass if the rule's behavior were removed or changed.

1. [attention · 4] **`evals/tools/test_lint_rules.py:12`** — test pins prose wording and a line-wrapped sentence rather than a contract
```
RESUME_RULES = ((".cursor/agents/references/dispatch.md", "A dispatch that ends with no reply is resumed once, never re-dispatched"),
                (".cursor/agents/crew-specwriter.md", "A critic that returns no reply gets one\n   resume, never a second dispatch"))
```
The test passes when a sentence is present verbatim, so it does not check that the orchestrator resumes once or never re-dispatches. Rewording the doc breaks the test while behavior is unchanged. A contradicting rule elsewhere in the file would not break it. The specwriter row embeds `\n   ` (a newline and three spaces), so re-wrapping or re-indenting the markdown fails it, though nothing contractual changed. This is the "test pinning prose beyond the contract" breach in the testing policy.
Fix: Pin only the contract tokens, such as the `deliver now` resume instruction, in a whitespace-normalized form (`" ".join(text.split())`). Alternatively, drop the test if the lint rules already cover the orchestrator files. If the sentence has to stay pinned, state why it is the contract.

2. [attention · 3] **`evals/tools/test_lint_rules.py:19`** — the `deliver now` check is file-wide and does not tie to the rule
```
assert rule in text and "`deliver now: " in text, path
```
The two conditions are checked independently, so the second can be satisfied by an unrelated mention elsewhere in the file. A failure also reports only `path`, not which condition failed. The docstring says crew-reviewer is covered through `dispatch.md`, but nothing checks that `crew-reviewer.md` references `dispatch.md`. If that link is removed, the test still passes.
Fix: Assert the two conditions separately with distinct messages. Add a row or check that `crew-reviewer.md` points to `dispatch.md`, or say in a comment why it needn't.

3. [nit · 3] **`evals/tools/test_lint_rules.py:11`** — the comment and the table are a fragile coupling
The `RESUME_RULES` tuple has one very long line. The docstring and the comment both restate the rule. This costs readability, and the restated rule can drift from the table.
Fix: Format the table one row per line and keep a single description of the rule.