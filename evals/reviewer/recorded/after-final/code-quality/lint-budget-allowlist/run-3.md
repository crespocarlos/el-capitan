Assessment: approve — the rule checks the declared budget, the turn margin and the stated budget as the change intends. The remaining problems are a crash path, a silent skip and missing tests.

Read beyond the package: `lint_prompts.py` (the excerpt only), and a glob for `.cursor/agents/*.md` and other lint files, which found none. `Findings`, `parse_frontmatter` and `rel` are not defined or imported in the excerpt. There is also no registration of `lint_turn_budget` and no test file in the tree. I could not check either against the real module.

1. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:25`** — body split can raise IndexError and crash the whole lint run
```
name, body = rel(root, path), text.split("\n---\n", 1)[1]
```
`parse_frontmatter` has already accepted the file. This line then re-derives the body with a different rule that needs `\n---\n`. A persona whose closing `---` is the last line with no trailing newline, or one saved with CRLF line endings, passes the parser and then raises `IndexError`. The linter then dies with a traceback instead of reporting a finding. Fix: take the body from `parse_frontmatter`, since the second return value is discarded as `_` and is probably it. Otherwise use `text.split("\n---\n", 1)[-1]` or a `partition` call.

2. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:23`** — a budgeted agent with broken frontmatter silently skips the rule
```
if error:
    continue
```
A listed persona whose frontmatter fails to parse produces no `persona-turn-budget` finding, so the "must declare" guarantee only holds if another rule reports the parse error. Nothing in the excerpt shows that rule. Fix: check `path.stem in BUDGETED_AGENTS` before the `continue` and emit a finding, or state in a comment which rule owns parse errors.

3. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:10`** — a stale allowlist entry fails silently
```
BUDGETED_AGENTS = ("reviewer-adversarial", ... "specwriter-scope")
```
The loop only visits files that exist. If a persona is renamed or deleted, its name stays in the tuple and nothing fails. A new reviewer that is not added to the tuple is never required to declare a budget. Fix: after the loop, report every name in `BUDGETED_AGENTS` that has no matching file. Alternatively, derive the set from the filename prefixes `reviewer-*` and `specwriter-*`.

4. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:16`** — new lint rule with no tests
There is no test in the diff for any of the rule's branches:
- a missing `tool_budget`, for a listed agent and for an unlisted one;
- `maxTurns` absent, at N+1, and at exactly N+2, which is the boundary;
- the stated budget absent, repeated, or different from the declared one;
- the early skip on a frontmatter error.

An implementation that changed `<` to `<=`, or that dropped the `[str(calls)]` equality, would pass every check that exists. Fix: add a table-driven test over small fixture agent files in the existing lint test module.

5. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:36`** — one message covers three different failures
```
f"say the budget once: \"stop calling tools at {calls}\""
```
The same message appears whether the phrase is missing, repeated, or states a different number than `tool_budget`. The author has to open the file to find out which of the three it is. Fix: report the found values, for example `found {STATED_BUDGET.findall(body)}, expected ['{calls}']`.