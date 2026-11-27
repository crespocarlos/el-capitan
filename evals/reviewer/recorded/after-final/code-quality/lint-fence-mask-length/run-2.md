Assessment: request-changes — the fence mask can invert on nested or longer fences and so hide real prose, and the new rule has no tests to catch that.
Read beyond the package: none. The directory holds only `lint_style.py`; `lint_files` and any tests or callers are not present.

1. [attention · 4] **`.agent/tools/maintenance/lint_style.py:34`** (fence mask) — fence close ignores fence length and allows an info string
```python
text = re.sub(r"^(\s*)(```|~~~).*?^\s*\2[^\n]*$", blank, text, flags=re.S | re.M)
```
A four-backtick fence that wraps a three-backtick example is common in prompt files. The mask closes at the inner three-backtick line, so the rest of the example is read as prose. The real four-backtick closer then opens a new "fence" that swallows the following prose up to the next fence line. The result is false positives inside the example and missed shouting in the prose after it. The closer also accepts trailing text, so an opening line such as "```python" inside a block ends it early.
Fix: capture the whole opening run and require a closer of the same character and at least that length with nothing after it, for example `^(\s*)(`{3,}|~{3,})[^\n]*\n.*?^\s*\2[`~]*\s*$`. Make the opener's own info string non-greedy, and add a test with a nested fence.

2. [attention · 4] **`.agent/tools/maintenance/lint_style.py:1`** (module) — a new rule with no tests
```python
SHOUTING = re.compile(r"\b(?:MUST|NEVER|ALWAYS|NOT(?! VERIFIED)|ONLY|DO|...
```
No test is in the change. Nothing checks that frontmatter, fences or inline code are masked, or that line numbers survive masking. Nothing checks the `NOT VERIFIED` exception either. A rewrite that drops masking, or one that breaks `line_no` alignment, would pass. The cases worth a table are a nested fence, an unclosed fence, CRLF input, a double-backtick span, and an uppercase word in prose that should be flagged.
Fix: add a table-driven test in the existing lint test module, with each case giving a masked-or-flagged expectation.

3. [attention · 3] **`.agent/tools/maintenance/lint_style.py:17`** (`SHOUTING`) — the word list flags ordinary uppercase and has an unexplained exception
```python
|NOT(?! VERIFIED)|ONLY|DO|DON'T|NO|...|ALL|ANY|EVERY
```
Short tokens such as `NO`, `DO`, `ALL`, `ANY` also match acronyms and literals in prose, for example SQL `ANY`, a `NO` status value or `ALL` as a mode name. Only `NOT VERIFIED` is exempt, and no comment says why. Maintainers will not know whether to extend the exemption or the list.
Fix: comment why `NOT VERIFIED` is allowed. Either drop the ambiguous short words or add a per-line opt-out, and cover both in the test table.

4. [nit · 4] **`.agent/tools/maintenance/lint_style.py:31`** (`mask`) — the `inline` flag has no caller that sets it
```python
def mask(text: str, inline: bool = True) -> str:
```
`lint_style` never passes `inline`, so `False` is unreachable here. A boolean that switches behaviour is a cost with no use. Also, `FRONTMATTER` needs `\n`, so CRLF files are never masked, and the inline pattern misses double-backtick spans.
Fix: remove the parameter until something needs it, and normalise line endings before masking.