Assessment: request-changes — the test pins exact prose from files that aren't in the package, and its assertion would pass for a rule that doesn't hold.
Read beyond the package: none. The working directory holds only `test_lint_rules.py`. The orchestrator files `dispatch.md` and `crew-specwriter.md` aren't there, so I couldn't read them.

1. [attention · 4] **`evals/tools/test_lint_rules.py:12`** (h1) — Test pins literal prose, including a line break and indentation, instead of the contract
```python
(".cursor/agents/crew-specwriter.md", "A critic that returns no reply gets one\n   resume, never a second dispatch"))
```
The rule string embeds `\n   ` (a hard wrap plus three spaces of indentation). Re-wrapping the paragraph, or changing the list indentation, fails the test even though the rule is unchanged. A reworded rule that still says "resume once" fails too. The test checks wording, not behaviour. Fix: assert on short stable tokens, such as `deliver now` and `resume`, or normalize whitespace with `" ".join(text.split())` before matching. Better, anchor on a named marker for the rule.

2. [attention · 4] **`evals/tools/test_lint_rules.py:19`** — The assertion doesn't tie the `deliver now` marker to the rule, and the message doesn't say which part failed
```python
assert rule in text and "`deliver now: " in text, path
```
The two substrings are checked independently anywhere in the file. A file that keeps the rule sentence but drops the resume instruction passes if `` `deliver now: `` appears anywhere else, for example in an unrelated example. When the test fails, the message is only the path, so you can't tell which condition broke. Fix: split it into two asserts, each with its own message, and require the marker near the rule, for example inside the same paragraph.

3. [nit · 3] **`evals/tools/test_lint_rules.py:10`** — The `crew-reviewer` half is tested through `dispatch.md`, not through `crew-reviewer.md`
The row for `dispatch.md` sits under a test whose docstring and the change description say "each orchestrator file". If `crew-reviewer.md` stops referencing `dispatch.md`, the test still passes. The reviewer rule then silently stops applying. Fix: add a check that `crew-reviewer.md` references `dispatch.md`, or put the reviewer row on its own file.