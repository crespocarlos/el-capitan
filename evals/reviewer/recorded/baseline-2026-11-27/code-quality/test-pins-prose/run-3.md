Assessment: request-changes — the test pins exact prose, including a hard line wrap, instead of the resume-once contract, and the files it reads are not in the case files.

1. [attention · 4] **`evals/tools/test_lint_rules.py:12`** — test pins prose wording, including a hard line wrap and indentation
```python
(".cursor/agents/crew-specwriter.md", "A critic that returns no reply gets one\n   resume, never a second dispatch"))
```
The assertion is a verbatim substring match on two English sentences. The specwriter string embeds `\n` plus three spaces of indentation, so it depends on where the markdown is wrapped. Any rewrap, reword or list renumbering fails the test while the rule is unchanged. A deleted rule with similar wording would still pass, so the test checks wording rather than behavior. This is the "test pinning prose" breach in the testing policy.
Fix: drop the sentence match. Assert the stable contract tokens instead: `deliver now` appears, and the file mentions resume. Or normalize whitespace (`" ".join(text.split())`) and match a short anchor phrase. A durable alternative is to move the rule into a machine-checked marker, such as a front-matter key or a fixed tag, and assert on that.

2. [attention · 3] **`evals/tools/test_lint_rules.py:19`** — conjoined assertion, weak failure signal, and no check of the "never re-dispatch" half
```python
assert rule in text and "`deliver now: " in text, path
```
`rule in text and X in text` reports only `path` on failure, so you can't tell which half broke. The `` `deliver now: `` check is a loose substring that may match unrelated text elsewhere in the file. Nothing distinguishes a file that says "resume once" from one that also permits a second dispatch.
Fix: assert the two conditions separately with messages naming the missing piece. Anchor the `deliver now` check inside the rule's section rather than anywhere in the file.

3. [nit · 3] **`evals/tools/test_lint_rules.py:10`** — the comment, the docstring and the test name each restate the rule
The comment, docstring and test name all say "resumed once with deliver now". The test also sits between the `ROOT` setup and `test_handoff`, away from related tests. Keeping one statement of the rule, near the table, avoids three copies drifting apart.
Fix: keep the comment and shorten the docstring.

4. [needs more info · 2] **`evals/tools/test_lint_rules.py:11`** — the referenced orchestrator files are absent from the working directory
The package says the diff leaves no other files unchanged, and a grep found no `dispatch.md` or `crew-specwriter.md` matches. The diff shows only the test file. If the rule text was not added in the same change, the test fails with `FileNotFoundError` or a missing-substring failure. I could not read the orchestrator files to confirm. Do both files exist with the exact strings, and does `crew-reviewer.md` actually route through `dispatch.md`?