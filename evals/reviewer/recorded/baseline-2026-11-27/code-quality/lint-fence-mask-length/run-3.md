Assessment: request-changes — the fence mask closes a longer fence at the first inner shorter fence, so the "code is exempt" promise fails, and the new module has no tests.

1. [blocking · 5] **`.agent/tools/maintenance/lint_style.py:38`** — fence mask ignores fence length, so nested fences leak into prose
```python
text = re.sub(r"^(\s*)(```|~~~).*?^\s*\2[^\n]*$", blank, text, flags=re.S | re.M)
```
The opener captures only three characters, so a four-backtick fence opens with the first three. Any line that begins with three backticks then closes it, including an inner example fence. Closing lines may also carry trailing text (`[^\n]*`), so an inner opener such as "```python" counts as a close. The rest of the outer fence is then linted as prose. Prompt files often show fenced examples inside longer fences, and those examples contain commands and constants such as `MUST` and `NEVER`. This gives false `no-shouting` findings in exactly the content the module says is exempt. The fix needs a regex with a backreference to the full run, and closing lines should allow only whitespace after the fence.

Fix: capture the whole fence run and require a closing run of the same character that is at least as long, with nothing after it:
```python
text = re.sub(r"^[ \t]*(?P<f>`{3,}|~{3,})[^\n]*\n.*?^[ \t]*(?P=f)[`~]*[ \t]*$", blank, text, flags=re.S | re.M)
```
Mixing backticks and tildes in the closing run needs care, so a per-character pattern is safer. Add a test with a four-backtick fence that contains a three-backtick fence.

2. [attention · 4] **`.agent/tools/maintenance/lint_style.py:1`** — new rule module ships with no tests
```python
"""The writing standard for prompt files: rules, agents, skills and their references (excerpt).
```
The diff adds only `lint_style.py`. Nothing checks that frontmatter, fences or inline code are masked, that `NOT VERIFIED` is allowed, or that reported line numbers match the source. The masking is the risky part, and finding 1 is the kind of defect a small fixture test would catch. Without a test, a plausible bad implementation (masking that shifts offsets, or an unmasked fence) passes unnoticed.

Fix: add tests in the existing lint test file. Cover masking, offset and line preservation, the `NOT VERIFIED` exception, and nested fences.

3. [nit · 3] **`.agent/tools/maintenance/lint_style.py:33`** — `inline` flag has no caller that passes `False`
```python
def mask(text: str, inline: bool = True) -> str:
```
The only caller uses the default, so the boolean parameter switches behavior that nothing uses. It adds a branch to read and test. Also, the inline-code pattern `` `[^`\n]+` `` does not handle double-backtick spans such as ``` ``a `b` `` ```, so a span of that kind can be partly exposed.

Fix: drop the parameter until something needs it, or add a caller and a test for it.