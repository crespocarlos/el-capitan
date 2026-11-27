Assessment: request-changes — the new rule is never called and uses names this file doesn't define, so it can't enforce anything as it stands.

1. [blocking · 4] **`.agent/tools/maintenance/lint_prompts.py:16`** — `lint_turn_budget` is defined but never called
```
def lint_turn_budget(root: Path) -> Findings:
```
A grep for `lint_turn_budget` finds only this definition. No runner in the file registers it, so the `persona-turn-budget` rule never fires and personas without `tool_budget:` pass unflagged. The visible file has no `main` or rule list, so the wiring may live in an unchanged file I couldn't see. Still, the change as shown doesn't register it.
Fix: add `lint_turn_budget` to wherever the other lint functions are invoked, such as `lint_native_tool_ids`. Add a test or fixture that triggers it.

2. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:25`** — body is re-split by hand instead of using the parser's result
```
frontmatter_text, _, error = parse_frontmatter(text)
...
name, body = rel(root, path), text.split("\n---\n", 1)[1]
```
`parse_frontmatter` already returns a second value, which is discarded as `_` and is probably the body. The manual split assumes an LF closing delimiter followed by a newline. A file ending in `\n---` with no trailing newline, or one using CRLF, raises `IndexError` and crashes the whole lint run. The same applies if the frontmatter holds a `---` line. `STATED_BUDGET` is also matched against whatever this split yields, so a wrong split gives wrong findings.
Fix: use the returned body, e.g. `frontmatter_text, body, error = parse_frontmatter(text)`, after confirming its return order.

3. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:22`** — `parse_frontmatter`, `rel` and `Findings` are not defined or imported in this file
```
frontmatter_text, _, error = parse_frontmatter(text)
```
The imports are only `re` and `Path`. `lint_native_tool_ids` already uses `rel` and `Findings`, so these may be defined elsewhere in the file. `parse_frontmatter` appears nowhere in the working directory, so it may be undefined. If it is, the function raises `NameError` on its first iteration.
Fix: import or define `parse_frontmatter`, and confirm its return shape.

4. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:34`** — frontmatter errors are skipped silently
```
if error:
    continue
```
A budgeted agent with broken frontmatter passes this rule. This is only fine if another rule reports the parse error for that file.
Fix: check that a separate rule reports it, or flag budgeted agents here.

5. [nit · 2] **`.agent/tools/maintenance/lint_prompts.py:8`** — a hard-coded agent allowlist must be edited by hand for each new reviewer
The tuple `BUDGETED_AGENTS` has to be updated whenever a persona is added. A new reviewer that is never added to it is exempt from the requirement. That is the same gap this rule was written to close.
Fix: derive the set from a filename prefix (`reviewer-*`, `specwriter-*`), or add a comment pointing to where new personas must be registered.