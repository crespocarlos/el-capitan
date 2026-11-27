Assessment: request-changes — the rule's allowlist and body-splitting can silently skip or crash on the agents it exists to check, and I see no tests for it.
Read beyond the package: none. The only file in the working directory is `lint_prompts.py`, so I could not check `parse_frontmatter`, `rel`, `Findings` or the rule registration.

1. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:26`** — body split crashes on a frontmatter-only file
```python
        if error:
            continue
        name, body = rel(root, path), text.split("\n---\n", 1)[1]
```
The split assumes a `\n---\n` closing delimiter. A file whose closing `---` is the last line with no trailing newline, or one using CRLF, may pass `parse_frontmatter` and then raise `IndexError`. The linter would then abort on that file instead of reporting a finding. The body is also re-derived by a different method than the one that parsed the frontmatter.
Fix: have `parse_frontmatter` return the body, or use `text.partition`/`split(..., 1)` with a length check, and `continue` or report when there is no body.

2. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:25`** — an unparseable budgeted agent passes silently
```python
        if error:
            continue
```
A listed agent whose frontmatter is malformed (a likely result of a bad edit) is skipped by this rule. The budgeted agent then gets no `tool_budget`, `maxTurns` or stated-budget check. This is fine only if another rule reports the parse error for sure.
Fix: if `path.stem in BUDGETED_AGENTS`, append a `persona-turn-budget` finding for the unparseable frontmatter before `continue`.

3. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:8`** — the hard-coded roster drifts and nothing notices a missing file
```python
BUDGETED_AGENTS = ("reviewer-adversarial", "reviewer-architecture", ...
```
The loop only visits files that exist. If a listed agent is renamed or deleted, its entry goes stale with no finding. A new `reviewer-*` agent is exempt until someone edits this tuple. The stated goal is that every reviewer persona declares a budget, and the tuple is a second place to keep in sync.
Fix: derive the set from the `reviewer-*` and `specwriter-*` filename prefixes, or assert that every name in the tuple has a file.

4. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:38`** — no tests for the new rule, and its rejections are the point
The rule rejects four cases: missing `tool_budget`, `maxTurns < N+2`, zero statements of the budget, and two or more. I cannot see any test that covers them. An implementation that checked `maxTurns >= N` instead of `N+2`, or that accepted a duplicated statement, would pass unnoticed.
Fix: add a table-driven test in the existing lint test module. Include the boundary cases `maxTurns == N+1` (rejected) and `maxTurns == N+2` (accepted), plus 0 and 2 statements.

5. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:36`** — `\b` and a plain `\d+` regex accept loose text
`stop calling tools at 8` also matches inside `stop calling tools at 8.5` and `at 80`-style prefixes only partly, and `\b` will match before `.`. The persona text in this very change ("Stop calling tools at 8 and write...") is fine. The loose match could wrongly accept a malformed statement.
Fix: use `(\d+)(?![\d.])` or require the statement to end with a non-digit, non-dot character.

Handoff to architecture: `.agent/tools/maintenance/lint_prompts.py:16` — I could not confirm that `lint_turn_budget` is registered in the lint runner, or that `Findings`, `rel` and `parse_frontmatter` are imported. The file shown has no definitions or imports for them. If the function is not registered, the rule never runs.