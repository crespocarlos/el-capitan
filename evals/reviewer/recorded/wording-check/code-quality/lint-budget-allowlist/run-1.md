Assessment: request-changes — the rule's coverage is incomplete (malformed or missing agents pass silently), it can crash on some files, and the diff adds no tests to show it rejects anything.

Read beyond the package: none (the only file present is the lint excerpt; `.cursor/agents` is absent from the working directory)

1. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:25`** — `split("\n---\n", 1)[1]` can raise IndexError and abort the whole lint
```python
if error:
    continue
name, body = rel(root, path), text.split("\n---\n", 1)[1]
```
`parse_frontmatter` decides whether the frontmatter is well formed, but this line re-finds the closing fence with a different rule. A persona whose closing `---` is the last line of the file with no trailing newline, or one that uses CRLF line endings, may parse cleanly and then raise IndexError here. One such file crashes the lint for every agent. The same function already treats the parse result as authoritative, so the body should come from it.
Fix: take the body from `parse_frontmatter`. If its return value does not include the body, split with `text.split("\n---", 1)` and a length check that reports a finding instead of raising.

2. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:23`** — an agent with broken frontmatter is skipped silently, even a budgeted one
```python
if error:
    continue
```
Suppose `reviewer-code-quality.md` has broken YAML frontmatter and so loses its `tool_budget`. This rule reports nothing, so the budget check passes for the agent it most needs to cover. The same gap exists when an allowlisted agent's file is renamed or deleted. `BUDGETED_AGENTS` is then never checked against the files that exist, so a missing agent gives no finding.
Fix: if `path.stem in BUDGETED_AGENTS`, append a `persona-turn-budget` finding before `continue`. After the loop, report any `BUDGETED_AGENTS` name that has no file.

3. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:26`** — a malformed `tool_budget` is treated as absent, with a misleading message
```python
budget = re.search(r"^tool_budget:[ \t]*(\d+)[ \t]*$", frontmatter_text, re.MULTILINE)
if not budget:
    if path.stem in BUDGETED_AGENTS: ... "declare tool_budget: N"
    continue
```
`tool_budget: "8"`, `tool_budget: 8 # comment` and `tool_budget: eight` all fail the regex. A budgeted agent is told to "declare" a key it already has. Any other agent with the same typo is skipped entirely, which contradicts the docstring's claim that any agent declaring a budget is held to the same checks. `maxTurns` has the same strictness, so `maxTurns: 10 # note` reads as missing and the message says "set maxTurns to at least 10".
Fix: match `^tool_budget:` loosely first, and if the value does not parse as an integer, report "tool_budget must be an integer". Allow an optional trailing comment in both regexes.

4. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:16`** — no test accompanies the new rule, and the rule's value is in what it rejects
The diff adds no test for `lint_turn_budget`. Several implementations would pass any test that only checks a good persona:
- one that ignores `REPLY_TURNS`;
- one that accepts `maxTurns == calls + 1`;
- one that accepts a budget stated twice or zero times;
- one that never flags an allowlisted agent missing the key.
The off-by-one at `<` and the exact-once check at line 35 are the branches that need cases.
Fix: add a small table-driven test over fixtures: `maxTurns` equal to N+2 passes and N+1 fails; the phrase appearing 0, 1 or 2 times; a mismatched stated number; a missing key on a budgeted versus a non-budgeted agent. Add it to the existing lint test file if one exists.

5. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:10`** — the hardcoded agent list duplicates the glob and will drift
Adding a new `reviewer-*` or `specwriter-*` persona does not extend the tuple. That persona can then ship without a budget, which is the case the rule exists to catch. The comment says "review lenses and spec critics", which suggests a name-prefix rule would match intent. The tuple also stops at the `specwriter-adversarial` and `specwriter-scope` critics, with no sign that this is the complete set.
Fix: derive the set from the `reviewer-*` and `specwriter-*` name prefixes, or add a comment saying that a new persona must be added to the tuple.

6. [nit · 2] **`.agent/tools/maintenance/lint_prompts.py:16`** — `Findings`, `parse_frontmatter` and `rel` are not defined or imported in this file, and nothing registers the rule
The file is labelled an excerpt, so these may live elsewhere. If they do not, the file raises NameError on import, because `Findings` appears in a signature that is not deferred, though `from __future__ import annotations` defers it. If the runner does not call `lint_turn_budget`, the rule never runs. This should be confirmed against the full module.