---
name: crew-commit
description: "Generate a semantic commit message and commit. Use when the user says 'commit', 'commit this', or asks for a commit message."
---

# Semantic Commit

## When Invoked

1. Check for staged changes: `git diff --staged --stat`
2. If nothing staged, run `git status --short` and show the user what's unstaged. Ask which files to stage — never `git add -A` without explicit approval (it can pick up .env files, debug logs, scratch files).
3. Read the full staged diff: `git diff --staged`
4. Read `~/.agent/tasks/$(basename $(git rev-parse --show-toplevel))/$(git branch --show-current)/SPEC.md` if it exists (for intent context)

## Commit Message Format

Single line. [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <imperative description>
```

Examples:
```
feat(evals): convert feature duplication evaluators to createPrompt pattern
fix(streams): handle empty feature array in duplication check
refactor(synthtrace): extract template generation into separate module
test(evals): add semantic uniqueness evaluator coverage
chore(deps): bump @kbn/inference-common to 1.4.0
```

### Types
- `feat` — new feature or capability
- `fix` — bug fix
- `refactor` — code change that neither fixes a bug nor adds a feature
- `test` — adding or updating tests
- `chore` — maintenance, dependency updates, config changes
- `docs` — documentation only
- `perf` — performance improvement

### Rules
- Imperative mood ("add", not "added" or "adds")
- No period at the end
- Max 72 characters total
- Scope from the primary directory or module changed, lowercase
- If SPEC.md exists, the message should reflect its goal
- Never multi-line for branch commits — the PR description carries the context

## Output

Present the proposed message and ask: "Look good?"

Only commit after the user approves:

```bash
git commit -m "<the message>"
```