Assessment: request-changes — the test pins exact prose, including a line break and indentation, instead of the resume rule, and it would stay green with the rule broken.

Read beyond the package: none. A grep for the phrases and a glob for `*.md` in the working directory found no orchestrator files. I could not check the pinned sentences against the files.

1. [attention · 4] **`evals/tools/test_lint_rules.py:11`** — The test pins exact prose, so rewording breaks it and a broken rule still passes
```python
"A critic that returns no reply gets one\n   resume, never a second dispatch"
...
assert rule in text and "`deliver now: " in text, path
```
The specwriter string embeds a newline and three spaces of indentation. Rewrapping that paragraph fails the test even though the rule is unchanged. The test also passes when the rule is wrong. A file that says "resumed twice" would pass as long as the sentence and `` `deliver now: `` both appear somewhere in it. For example, `deliver now: ` could appear in an unrelated place, or the sentence could sit in a "don't do this" example. The test pins wording beyond the contract, which the testing policy rules out.
Fix: assert the contract, not the sentence. Check that each file matches a whitespace-tolerant pattern such as `re.search(r"no\s+reply.*resum\w+.*never", text, re.S | re.I)`. Or give the rule a stable marker, such as a heading or an anchor id, and assert on that. Normalize whitespace with `" ".join(text.split())` before comparing.

2. [nit · 3] **`evals/tools/test_lint_rules.py:19`** — The compound assert hides which half failed, and the `deliver now` check is not tied to the rule
```python
assert rule in text and "`deliver now: " in text, path
```
The failure message is only the path. The reader cannot tell whether the rule sentence or the `deliver now` token is missing. The trailing space and backtick in `` `deliver now: `` also depend on the exact formatting of the instruction.
Fix: use two asserts with messages, for example `assert rule in text, f"{path}: resume rule missing"` and `assert "deliver now" in text, f"{path}: no deliver now instruction"`.

3. [nit · 2] **`evals/tools/test_lint_rules.py:7`** — The new test sits in the lint-rules test module with no stated reason
The test checks prompt-file prose, not lint rules. The module's other tests (`test_handoff`) use the `HANDOFFS` table and a `tmp` fixture. I could not see the rest of the file, so I could not check whether another module already holds prose-presence checks.
Fix: if a module for orchestrator-file checks exists, move the test there. Otherwise say in a comment why it belongs in this module.