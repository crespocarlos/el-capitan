---
name: crew-remember
description: "Promote a pattern, convention, or rule into persistent config (CLAUDE.md or AGENTS.md). Use when the user says 'remember this', 'add to CLAUDE.md', 'promote this pattern', or when crew-journal/crew-creative surfaces candidates."
---

# Promote to Rules

## When Invoked

### Step 1 — Identify the rule

Extract the pattern, convention, or rule to promote. Sources:

- User says it directly: "remember that we always use Emotion for styles"
- crew-journal flagged it in `**Promote to rules:**`
- crew-creative flagged it in `**Patterns emerging:**` (3+ occurrences)

Formulate it as a clear, actionable rule. One sentence preferred. Example:
> "Always use Emotion for component styles; never use inline `style=` attributes."

### Step 2 — Determine the target

Ask if not obvious:

- **Global convention** → `~/.claude/CLAUDE.md` (applies to all repos/projects)
- **Project-specific** → the repo's `AGENTS.md` (applies to one repo)

If the rule references a specific repo pattern (naming conventions, test structure, dependency choices), it belongs in `AGENTS.md`. If it's about how the user works in general (agent preferences, commit style, review approach), it goes in `CLAUDE.md`.

### Step 3 — Check for duplicates

Read the target file and check whether the rule (or a similar one) already exists. If so, tell the user:
> "This is already covered: [existing rule]. Want to update it instead?"

### Step 4 — Append the rule

Add the rule to the appropriate section of the target file. If the file has no clear section structure, append to the end.

Present the addition and ask: "Look good?"

Only write after the user approves.

### Step 5 — Confirm

Show what was added and where:
> "Added to ~/.claude/CLAUDE.md: [rule summary]"

## Rules

- Always ask before writing — same pattern as crew-commit
- One rule at a time; if the user has multiple, process them sequentially
- Rules should be specific and actionable, not vague guidance
- Never overwrite existing rules — append or offer to update
- If CLAUDE.md or AGENTS.md doesn't exist, create it with a minimal header
