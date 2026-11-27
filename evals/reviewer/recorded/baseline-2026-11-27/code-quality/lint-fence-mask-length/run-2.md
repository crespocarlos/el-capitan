Assessment: request-changes — the fence mask ignores fence length and accepts info-string lines as closers, so a nested fence can flip masking for the rest of a file. The module also ships with no tests.

1. [blocking · 4] **`.agent/tools/maintenance/lint_style.py:38`** — fence mask closes on any fence line, ignoring fence length and info strings
```python
text = re.sub(r"^(\s*)(```|~~~).*?^\s*\2[^\n]*$", blank, text, flags=re.S | re.M)
```
The opener matches only three backticks, and the closer is any later line that starts with those three characters, followed by anything (`[^\n]*`). Take a four-backtick fence that holds a three-backtick example, which is common in prompt files that document markdown. The mask ends at the inner "```bash" line. The example body is then read as prose and flagged for MUST/NEVER. The inner closing fence then opens a new "fence" that swallows real prose up to the next fence line. After that, masking is inverted for the rest of the file, giving both false positives and missed shouting. CommonMark requires the closer to use the same character, be at least as long as the opener, and carry no info string.
Fix: capture the whole opening run and require a closer at least that long with nothing after it, for example:
`r"^[ \t]*(?P<f>`{3,}|~{3,})[^\n]*\n.*?^[ \t]*(?P=f)[`~]*[ \t]*$"`
You could also use a line-by-line state machine. Add a regression case for a four-backtick fence that contains a three-backtick block.

2. [attention · 4] **`.agent/tools/maintenance/lint_style.py:1`** — no tests for the masking or the rule
```python
def mask(text: str, inline: bool = True) -> str:
def lint_style(root: Path) -> Findings:
```
The masking is the risky part, and finding 1 is exactly the failure a test would catch. There are no tests for any of these cases:
- frontmatter
- fenced code
- nested or unclosed fences
- inline code
- the `NOT VERIFIED` lookahead
- line-number preservation
- the `fixtures` exclusion

Fix: add a test file beside the other lint tests (or in the existing one). Use one table-driven mask test, one test that line numbers survive masking, and one end-to-end `lint_style` test on a tmp tree.

3. [nit · 3] **`.agent/tools/maintenance/lint_style.py:36`** — `inline` is a boolean that switches behavior and has no caller
```python
def mask(text: str, inline: bool = True) -> str:
```
`lint_style` is the only caller and uses the default. The flag adds a branch that nothing exercises. The unused capture group `(\s*)` in the fence regex adds noise too.
Fix: drop the parameter until a caller needs it, and remove the unused group.

4. [nit · 2] **`.agent/tools/maintenance/lint_style.py:39`** — inline-code and frontmatter masks miss common forms
```python
re.sub(r"`[^`\n]+`", blank, text)
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
```
Double-backtick spans such as ``` ``a `b` `` ``` are not masked as one span. CRLF files and frontmatter at end of file with no trailing newline are not masked either. Each of these produces false positives on text that is meant to be exempt.
Fix: use `` (`+)(?:(?!\1).)+?\1 `` for inline spans and `\r?\n` in the frontmatter pattern.