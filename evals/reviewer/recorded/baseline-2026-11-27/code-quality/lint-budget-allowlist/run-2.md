Assessment: comment — the rule matches its stated contract, but the diff has no test and no registration for `lint_turn_budget`, and the real agent files and caller are not in the package.

1. [needs more info · 3] **`.agent/tools/maintenance/lint_prompts.py:16`** — `lint_turn_budget` is defined but I can't see it called or tested
```python
def lint_turn_budget(root: Path) -> Findings:
```
Grep finds only the definition in the one file present. The diff adds no runner entry and no test. If the lint driver has an explicit list of rules, `persona-turn-budget` never runs and every persona can drift without a failure. Nothing exercises the pass and fail branches: a missing `tool_budget`, a low `maxTurns`, and a budget stated zero times or twice. Question: is the rule registered in the driver, and is there a fixture test for those cases? If not, the rule is dead code and the change does not achieve its stated goal.

2. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:25`** — body extraction can raise `IndexError` and abort the whole lint run
```python
name, body = rel(root, path), text.split("\n---\n", 1)[1]
```
`parse_frontmatter` returned no error, but this separate split assumes the closing fence is followed by `\n`. A file whose frontmatter closes at EOF, or one with CRLF line endings, makes `[1]` raise. The lint then crashes instead of reporting a finding. Frontmatter is also parsed in one place and split in another, so the two can disagree.
Fix: take the body from `parse_frontmatter`'s second return value (`_`) if it is the body. Otherwise use `text.partition("\n---\n")[2]`, which never raises.

3. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:28`** — a renamed or deleted agent silently drops out of enforcement
```python
if path.stem in BUDGETED_AGENTS:
```
`BUDGETED_AGENTS` is checked only against files that exist. If `reviewer-code-quality.md` is renamed or removed, its allowlist entry matches nothing and no finding appears. The `tool_budget` requirement then lapses without notice. This is the same failure the rule exists to prevent.
Fix: after the loop, report any `BUDGETED_AGENTS` name with no file, for example `findings.append((f".cursor/agents/{missing}.md", 1, "persona-turn-budget", "budgeted agent file not found"))`.

4. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:36`** — the message does not say what was found
```python
f"say the budget once: \"stop calling tools at {calls}\""
```
This one message covers three cases: the phrase is absent, it appears twice, or it states a different number. An author who wrote "stop calling tools at 6" against `tool_budget: 8` is told only to say it once. The cost is a guessing step in a lint meant to be self-explanatory.
Fix: report the values found, for example `f"stated budgets {found}; expected exactly one \"stop calling tools at {calls}\""`.