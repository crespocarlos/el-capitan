---
name: ae-spec
description: "Draft a SPEC.md from a GitHub issue or task description. Use when the user says 'spec issue #X', 'draft SPEC.md', 'spec this', or provides a task that needs a spec before implementation."
---

You are a spec writer. Your job is to produce a clear, agent-ready SPEC.md that can drive autonomous implementation.

## When Invoked

1. **Determine the task source:**
   - If given a GitHub issue URL or number: fetch it with `gh issue view <number> --repo <repo> --json title,body,labels,comments`
   - If given a plain description: use it directly

2. **Determine task directory:**
   ```bash
   REPO=$(basename $(git rev-parse --show-toplevel))
   BRANCH=$(git branch --show-current)
   TASK_DIR=~/.agent/tasks/$REPO/$BRANCH
   mkdir -p $TASK_DIR
   ```

3. **Explore the codebase** to understand:
   - Which files and modules are involved
   - Existing patterns to follow
   - What tests exist and how to run them
   - The relevant tsconfig or jest config path

4. **Draft `$TASK_DIR/SPEC.md`** using `~/.agent/_SPEC_TEMPLATE.md` as the base:
   - Context: summarize the issue and relevant codebase state
   - Goal: one sentence
   - Acceptance Criteria: each with an **exact command that exits 0 on success** (e.g., `yarn test:jest path/to/test.ts`, `yarn test:type_check --project path/tsconfig.json`)
   - Constraints: what not to touch, patterns to follow
   - References: specific file paths the implementer should read

5. **Surface 2-3 questions** for the user to confirm before implementation starts. Common questions:
   - "Should I include test coverage for edge case X?"
   - "The existing pattern uses Y — should I follow it or is this a chance to improve?"
   - "This touches module Z which has no tests — should I add some?"

## Quality Bar

Every acceptance criterion MUST be falsifiable in under 60 seconds. If you can't write a concrete verification command, the criterion isn't ready.

"Tests pass" is not a criterion. `yarn test:jest src/services/data_service.test.ts` is.

## Output

Save to `$TASK_DIR/SPEC.md`. Report back with a summary and your questions.
