---
name: crew-commit
description: "Generate a semantic commit message and commit. Trigger: 'crew commit'."
---
**Workflow**: build | **Stage**: commit

# Semantic Commit

## When Invoked

### Step 1: Check staged changes

Run `git diff --staged --stat`. If nothing staged, run `git status --short` and show the user what's unstaged. Ask which files to stage — never `git add -A` without explicit approval (it can pick up .env files, debug logs, scratch files).

### Step 2: Read the diff

Read the full staged diff: `git diff --staged`.

For intent context, find the active SPEC.md:

```bash
if [ -n "${CREW_TASK_DIR+x}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
else
  TASK_DIR=$(~/.agent/tools/resolve-task-dir.py) || exit 1
  export CREW_TASK_DIR="$TASK_DIR"
fi
```

If `$TASK_DIR` is non-empty, read it for intent context.

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

### Step 2b: Out-of-scope check

Before proposing the commit message, check for out-of-scope modifications. `TASK_DIR` was already resolved in Step 2 above.

If `$TASK_DIR/BASELINE.diff` exists:

1. List currently modified files: `git diff --name-only HEAD`
2. For each modified file, check if its name (basename or relative path) appears as a literal string in `$TASK_DIR/SPEC.md`:
   ```bash
   grep -q "<filename>" "$TASK_DIR/SPEC.md"
   ```
3. For each modified file whose name does **not** appear as a literal string in SPEC.md, emit:
   > "Out-of-scope warning: [file] was modified but is not referenced in SPEC.md."

Surface all warnings before proposing the commit message. The user decides whether to proceed, remove the files from staging, or update the spec.

### Step 3: Propose and commit

Present the proposed message and ask: "Look good?"

Only commit after the user approves:

```bash
git commit -m "<the message>"
```

After a successful commit, log the transition using the already-resolved `$TASK_DIR`:

```bash
if [ -n "$TASK_DIR" ]; then
  ~/.agent/tools/log-progress.py "$TASK_DIR" "COMMITTING: committed $(git rev-parse --short HEAD)"
fi
```

> Next: run `crew open pr` to continue.