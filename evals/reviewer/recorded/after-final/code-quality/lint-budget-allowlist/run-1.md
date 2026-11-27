Assessment: request-changes — the rule matches the stated goal, but it has no test and no visible caller, and it can crash on a persona with an empty body.
Read beyond the package: `lint_prompts.py` (full file), a Glob for tests of `lint_prompts`, a Grep for callers of `lint_turn_budget`.

1. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:25`** — `split("\n---\n", 1)[1]` raises IndexError on a file that ends at its closing fence
```
name, body = rel(root, path), text.split("\n---\n", 1)[1]
```
A persona whose frontmatter closes with `---` at end of file, with no trailing newline or body, passes `parse_frontmatter`. The split then returns one element and `[1]` raises IndexError, so the whole lint run crashes instead of reporting a finding. CRLF files fail the same way. This code re-finds the fence itself instead of taking the body from the parser that already found it.
Fix: take the body from `parse_frontmatter`, or use `text.split("\n---\n", 1)[-1]` after confirming the fence is present.

2. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:16`** — new lint rule with no test
```
def lint_turn_budget(root: Path) -> Findings:
```
The Glob found no test file for `lint_prompts`, and the diff adds none. A rule that only rejects needs cases showing what it rejects:
- a missing `tool_budget` on a budgeted stem;
- `maxTurns` equal to N+1;
- a missing `maxTurns`;
- a stated budget of zero, two, or a different number;
- a non-budgeted agent that declares a budget.

Without them, a rule that always returns `[]` or never reads `STATED_BUDGET` would pass. The off-by-one at `calls + REPLY_TURNS` and the `!= [str(calls)]` comparison are both unguarded.
Fix: add a table-driven test over temporary agent files, in the existing lint test module if there is one.

3. [needs more info] **`.agent/tools/maintenance/lint_prompts.py:16`** — nothing visible calls `lint_turn_budget`
Grep finds only the definition, and the file calls itself an excerpt. If the rule is not added to the runner or rule list, it never runs and the change enforces nothing. Is it registered elsewhere? If not, the lint is dead code.

4. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:26`** — the regex is strict, and the resulting message misleads
`tool_budget: 8  # why` or a quoted value fails the `(\d+)[ \t]*$` match. A budgeted agent then gets "declare tool_budget: N" although it already declares one. Cost: someone adds the budget and still gets told to add it. Fix: use a message such as "tool_budget must be a bare integer".

5. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:10`** — a renamed or removed agent in `BUDGETED_AGENTS` goes unnoticed
The loop only visits files that exist, so a stem with no matching file is never reported. Renaming `reviewer-code-quality` silently drops its enforcement. Fix: report any entry in `BUDGETED_AGENTS` that has no matching file.