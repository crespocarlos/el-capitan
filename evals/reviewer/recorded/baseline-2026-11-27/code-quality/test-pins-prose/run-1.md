Assessment: request-changes — the test pins exact prose, including a hard line wrap, so it breaks on rewording and doesn't check that the orchestrators actually resume once.

1. [attention · 4] **`evals/tools/test_lint_rules.py:11`** — test pins prose wording, including a hard line wrap
```
RESUME_RULES = ((".cursor/agents/references/dispatch.md", "A dispatch that ends with no reply is resumed once, never re-dispatched"),
                (".cursor/agents/crew-specwriter.md", "A critic that returns no reply gets one\n   resume, never a second dispatch"))
```
The test asserts verbatim sentences from two markdown files. The specwriter string embeds `\n   ` (a newline plus three spaces of indentation), so reflowing the paragraph or rewording a word fails the test even when the rule is intact. The contract is "resume once with `deliver now`, never re-dispatch", and these strings don't test that. They only detect edits to the wording. The second assertion, `"`deliver now: " in text`, only checks that the phrase appears somewhere in the file. It doesn't tie the phrase to the rule, so an unrelated mention satisfies it.
Fix: assert on stable tokens instead of whole sentences. For example, check that each file contains `deliver now` and the word `resume`, matched with whitespace-normalized text (`" ".join(text.split())`). Alternatively, drop the test and rely on the behavioral eval that exercises the orchestrators.

2. [nit · 3] **`evals/tools/test_lint_rules.py:19`** — combined assertion hides which part failed
```
assert rule in text and "`deliver now: " in text, path
```
The message is only `path`, so a failure doesn't say whether the rule sentence or the `deliver now` token was missing. Someone debugging has to open the file to find out.
Fix: use two separate asserts, each with a message naming what was missing.

3. [needs more info · 2] **`evals/tools/test_lint_rules.py:11`** — the target markdown files aren't in the package
The working directory contains only the test file. I couldn't confirm that `dispatch.md` and `crew-specwriter.md` contain these exact strings, or that `crew-reviewer.md` actually routes through `dispatch.md`. If the strings are absent or the paths are wrong, the test fails on the first run. If `crew-reviewer.md` doesn't reference `dispatch.md`, the docstring's claim that this test covers crew-reviewer is false. Can you confirm the strings, and that crew-reviewer links to `dispatch.md`?