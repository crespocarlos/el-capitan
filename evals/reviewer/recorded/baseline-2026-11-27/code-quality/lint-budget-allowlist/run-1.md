Assessment: approve — the rule checks what the change describes (`tool_budget` present, `maxTurns >= N+2`, budget stated once). The remaining issues are small robustness and test gaps.

1. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:25`** — body is re-split with a literal delimiter instead of reusing the frontmatter parser
```python
name, body = rel(root, path), text.split("\n---\n", 1)[1]
```
`parse_frontmatter` has already decided where the frontmatter ends. This line applies a second, independent rule: a literal `"\n---\n"`. A file that passes the parser but doesn't match the literal raises `IndexError` and crashes the whole lint run instead of producing a finding. That includes CRLF line endings and a closing `---` at EOF with no trailing newline. The parser's contract isn't visible in this excerpt, so I can't confirm it can disagree with the split.
Fix: take the body from `parse_frontmatter` if it returns it (the discarded middle element of the tuple, if that is the body). Otherwise use `text.split("\n---\n", 1)[-1]` or guard the split, so a malformed file yields a finding rather than a traceback.

2. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:16`** — no test for the new rule
```python
def lint_turn_budget(root: Path) -> Findings:
```
The diff adds a rule with four failure branches and no test. The branches are a missing `tool_budget` on an allowlisted agent, a missing or too-small `maxTurns`, a budget stated zero times, and a budget stated twice or with a different number. The diff also adds no test for the exemption of non-allowlisted agents without a budget. Without a test, a regression such as `<` becoming `<=` or the `findall` comparison loosening passes silently.
Fix: add one parametrized table test over fixture agent files, one row per branch, plus one passing case. Put it in the existing lint test module if there is one.

3. [nit · 2] **`.agent/tools/maintenance/lint_prompts.py:35`** — the same message is used for a missing statement and for a duplicate or wrong one
```python
if STATED_BUDGET.findall(body) != [str(calls)]:
```
The `findall(...) != [str(calls)]` check fires for zero matches, two matches, and a mismatched number. All three get "say the budget once". A reader whose file states `at 8` twice, or `at 6` against `tool_budget: 8`, has to work out which case they hit.
Fix: split the check into "found none", "found a different number", and "found more than once", or include the matches found in the message.