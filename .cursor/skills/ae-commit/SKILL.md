---
name: ae-commit
description: "Generate a semantic commit message and commit. Use when the user says 'commit', 'commit this', or asks for a commit message."
---

# Semantic Commit

## When Invoked

1. Check for staged changes: `git diff --staged --stat`
2. If nothing staged, stage all changes: `git add -A`
3. Read the full staged diff: `git diff --staged`
4. Read `~/.agent/tasks/$(basename $(git rev-parse --show-toplevel))/$(git branch --show-current)/SPEC.md` if it exists (for intent context)

## Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

<body — what changed and why, 2-4 lines max>
```

### Types
- `feat` — new feature or capability
- `fix` — bug fix
- `refactor` — code change that neither fixes a bug nor adds a feature
- `test` — adding or updating tests
- `chore` — maintenance, dependency updates, config changes
- `docs` — documentation only
- `perf` — performance improvement
- `style` — formatting, missing semicolons, etc.

### Scope
Derive from the primary directory or module changed. Use lowercase, no spaces.

### Rules
- Subject line: imperative mood, no period, max 72 chars
- Body: explain what and why, not how
- If SPEC.md exists, reference the goal in the body
- Never include file lists — `git log --stat` already shows that

## Output

Present the proposed commit message and ask: "Look good?" 

Only commit after the user approves. Use:

```bash
git commit -m "$(cat <<'EOF'
<the message>
EOF
)"
```
