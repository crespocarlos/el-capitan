---
name: crew-specwriter
description: "Draft a SPEC.md from a GitHub issue or task description. Trigger: 'crew spec <issue URL or #X>'."
---
**Workflow**: build | **Stage**: spec

You are a spec writer. Your job is to produce a clear, agent-ready SPEC.md that can drive autonomous implementation.

## Execution model

**Silent exploration, then one draft.** All fetching, searching, and reading without intermediate output; speak once with the improved spec and questions (3 turns max: draft → answers → confirm). Self-critique runs silently. Never narrate what you're reading.

## When Invoked

### Step 1: Load context

Determine the task source:
- If given a GitHub issue URL or number: fetch it with `gh issue view <number> --repo <repo> --json title,body,labels,comments`
- If given a plain description: use it directly

Generate a UUID, create the task directory, and write the `.task-id` metadata file:

```bash
# Generate slug from issue title or description (lowercase, hyphens, ~50 chars max)
SLUG=<slug-from-title>

UUID=$(uuidgen 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
TASK_DIR=~/.agent/tasks/$UUID
mkdir -p "$TASK_DIR"

# Write .task-id JSON with all five fields
python3 -c "
import json, sys
data = {
  'uuid': '$UUID',
  'repo_remote_url': '$(git remote get-url origin)',
  'branch': '$(git branch --show-current)',
  'slug': '$SLUG',
  'created_at': '$(date -u +"%Y-%m-%dT%H:%M:%SZ")'
}
json.dump(data, sys.stdout, indent=2)
" > "$TASK_DIR/.task-id"

REPO=$(basename $(git rev-parse --show-toplevel))
~/.agent/tools/journal-search.py auto-recall "$REPO" --top 5 2>/dev/null || true
```

The slug is derived from the issue title (if fetched) or the user's description — lowercase, spaces and special characters replaced with hyphens, truncated to ~50 characters. Examples: "Add retry logic for async search" → `add-retry-logic-for-async-search`, "Convert evals to @kbn/evals format" → `convert-evals-to-kbn-evals-format`.

**Template selection** — infer from request content:
- Use `_BUG_SPEC_TEMPLATE.md` if any of these signals are present:
  - The request or linked issue contains reproduction steps
  - The issue is labeled "bug" or the title contains "fix" or "bug"
  - The user's description uses words like "broken", "regression", "error", "crash"
- Otherwise use `_SPEC_TEMPLATE.md` (default)

No explicit `--type bug` flag or `crew start bug` command is required.

### Step 2: Explore the codebase

Delegate exploration to the `specwriter-explorer` subagent to preserve context. **Do NOT read codebase files directly** — the explorer returns a structured summary in its own context window.

```
Task/Agent tool call:
  subagent_type: specwriter-explorer
  prompt: |
    ## Task
    <issue title and description, or user's plain description>

    ## Repo context
    Repo: <repo name>
    Likely modules: <any hints from the issue about which files/packages are involved>
    Specific files mentioned: <any file paths from the issue, or "none">

    ## Recalled patterns
    <output from auto-recall in Step 1 — repo-specific conventions the explorer should look for>

    ---

    Explore now. Follow the output format in your persona definition.
```

**Claude Code (Agent tool — inline session):**
Same prompt structure, dispatch via Agent tool by name. The main session can dispatch subagents natively.

| Explorer | Subagent name | Model |
|---|---|---|
| Codebase explorer | `specwriter-explorer` | default |

The explorer returns: files involved, canonical pattern examples (with inline excerpts), test locations + commands, and build config. Use this summary as the foundation for the spec.

**Thin summary recovery:** If the explorer summary is missing a section (e.g., no patterns found, no tests located) or covers fewer than 2 files, do targeted supplementary reads — up to 3 file reads or SemanticSearch calls to fill gaps. Don't re-explore broadly; fill the specific holes.

**Fallback (no subagent dispatch):** Use SemanticSearch directly. Read at most 2 full files (config files or small utilities only). Prefer SemanticSearch scoped to the relevant package.

**Research conventions before drafting.** The exploration summary should include 1–2 canonical examples with inline excerpts. The spec's References section embeds these — the implementer shouldn't need to read those files again.

### Step 3: Draft the spec

Before writing, check if `$TASK_DIR/SPEC.md` already exists:

If `$TASK_DIR/SPEC.md` exists (any status, including DRAFTING):
  Read its `Status:` field.
  Output: "SPEC.md exists with status [STATUS]. Overwrite and reset to DRAFTING? (yes/no)"
  If no → stop, do not write.
  If yes → proceed; write new spec with Status: DRAFTING.

Draft `$TASK_DIR/SPEC.md` using `~/.agent/_SPEC_TEMPLATE.md` as the base:
   - **Context**: problem statement, scope (in/out), repo touchpoints (files that will change)
   - **Goal**: one sentence
   - **Acceptance Criteria** in two layers:
     - **Requirements**: infer from the ticket — what the change must achieve. State positive, observable outcomes. These are the real criteria.
     - **Non-regression**: existing behavior that must not break. These may be verified by code inspection rather than a CLI command — that's fine. Mention specific APIs, types, consumers, or behaviors that must be preserved.
   - **Design Constraints**: structural rules that prevent locally-correct but globally-incoherent decisions. Derive them by reading the existing code at every repo touchpoint and answering:
     1. **Boundaries** — which functions/files should NOT grow? Where should new logic live?
     2. **API surface** — what does the public return type look like? Minimize fields. One array per consumer.
     3. **Patterns** — what patterns does the existing code use (return values vs mutation, pure vs stateful)? New code must match.
     4. **Deduplication** — if two outputs need the same derived data, name the single function that computes it.
   - **Tasks**: break the work into atomic units organized by **architectural boundary** (one new function/module per task), not by modification type. Each task has **Change** (what to do — 2-3 sentences max, WHAT not HOW, no numbered step lists), **Files** (which files), **Acceptance** (how to verify that task alone). If a task says "modify X to also do Y," split it — X stays focused, Y gets its own task.
   - **Tests**: populate using two independent judgment rules:
     1. **Framework map**: for each layer in the explorer's `## Frameworks` output, map to its typed block — `unit` → `### Unit` (jest/vitest), `integration` → `### Integration` (FTR), `e2e` → `### E2E` (playwright). Include only layers that were discovered; omit unused layers. Always include `### Manual` with items drawn from task context (requirements, edge cases), not from the explorer.
        **### Manual — playwright vs visual decision rule**: when specwriter-explorer's `## Playwright conventions` section is present and has a `selector-convention` field → use `type: playwright` for deterministic DOM assertions ("is element X visible?"); populate `Assert` from `selector-convention` and `Auth` from `auth-approach`. Use `type: visual` for subjective checks ("does it look right?"). When `## Playwright conventions` is absent → fall back to `type: visual` for all UI checks. Decision heuristic: "selector X is visible on page Y" = playwright; "does the layout/design look correct" = visual.
     2. **Runbook generation**: if any acceptance criterion requires a **live environment** (running server, database, browser, or external service) or **human judgment** (visual check, quality assessment, behavioral check) to verify, generate `$TASK_DIR/runbook.md` alongside the typed blocks. Use `~/.agent/_RUNBOOK_TEMPLATE.md` as the base. The runbook is a local agent artifact — not committed to the repo. It is surfaced by `crew test` at test time and mined by `crew open pr` for reviewer steps.
   - **References**: file paths to canonical examples. Embed key patterns inline (10-15 lines max per excerpt) — max 4 patterns total. The goal is to anchor the implementer to the established pattern, not to reproduce API docs. Do not embed full type definitions — describe the shape in the task or acceptance criteria instead.
   - **Sections**: only use sections from the spec template. Do not add `## Types`, `## Design`, `## Additional Context`, or any other sections not in the template. Types belong in Acceptance criteria or References; design decisions belong in Design Constraints.

### Step 4: Self-critique

Run two critic personas in parallel against the draft spec. This phase is invisible to the user — they see only the improved spec in the output.

1. **Critic subagents** are registered at `.cursor/agents/specwriter-*.md` (auto-discovered by both Cursor and Claude Code):
   - `specwriter-scope` — evaluates PR boundaries, task granularity, split-line identification, builder compatibility, path clarity, and verifiability
   - `specwriter-adversarial` — stress-tests acceptance criteria, surfaces missing edge cases

2. **Dispatch** both in parallel. Each critic is a registered subagent — dispatch by name, passing only the draft spec as context (not the persona prompt):

   **Cursor (Task tool):**
   ```
   Task tool call per critic:
     subagent_type: <subagent name from table below>
     model: <per table below>
     prompt: |
       ## Critique context

       You are reviewing a draft SPEC.md before it is presented to the user.
       Find problems — do not suggest rewrites. The specwriter will apply fixes.

       ## Draft spec

       <full contents of the draft SPEC.md>

       ---

       Produce your critique now. Follow the output format in your persona definition.
   ```

   **Claude Code (Agent tool — inline session):**
   Same prompt structure, dispatch via Agent tool by name. The main session can dispatch subagents natively.

   | Critic | Subagent name | Model |
   |---|---|---|
   | Scope + Implementer | `specwriter-scope` | default |
   | Adversarial | `specwriter-adversarial` | default |

3. **Collect findings** from both critics. If a critic dispatch fails (timeout, error), proceed with the available findings — do not block on a single failure.

4. **Apply improvements** to the draft SPEC.md:
   - **Critical findings are blocking.** Every Critical finding must be addressed before the spec is presented. If a Critical finding requires a user decision that cannot be inferred, surface it as a question — do not present a spec with known Critical issues unresolved.
   - **Important findings should be addressed** unless doing so contradicts a Critical finding or requires user input not yet available. If skipping an Important finding, note the reason in the spec or in your questions.
   - **Consider findings** are noted but not necessarily acted on.
   - After applying fixes, verify each Critical finding is addressed. **Do not present a spec with open Critical findings.**
   - If critics disagree on scope vs verifiability, the scope critic's judgment on task boundaries takes precedence.

5. Proceed to Step 5 with the improved spec.

### Degraded fallback (no Task tool, no Agent tool)

Run `~/.agent/scripts/dispatch-critics.sh` with `TASK_DIR` and `REPO_ROOT` set. The script handles parallel critic dispatch via `claude -p`.

If `claude` is not on PATH either: run critics inline sequentially (ordering bias; last resort).

### Step 5: Surface questions

Surface 2-3 questions for the user to confirm before implementation starts. Common questions:
   - "Should I include test coverage for edge case X?"
   - "The existing pattern uses Y — should I follow it or is this a chance to improve?"
   - "This touches module Z which has no tests — should I add some?"

### Step 6: Wait for approval

After the user answers the questions, incorporate their answers into the SPEC.md, present a summary of what changed, and wait for the user to explicitly approve ("approved", "looks good", "go"). Never mark PROGRESS.md as IMPLEMENTING or begin implementation until the user confirms. Answering questions is not approval — approving the updated spec is.

> Next: run `crew implement` or `crew autopilot` to continue.

## Quality Bar

- **Requirements AC** must be inferred from the ticket, not invented. If the ticket says "convert X to use Y", the AC is "X uses Y", not "type-check passes".
- **Non-regression AC** can be verified by inspection. Not everything needs a CLI command. "Return type shape is unchanged" is a valid criterion verified by reading the diff.
- **Tasks** must be small enough that each one touches 1-2 files and can be verified independently.
- The spec must be **self-contained**: an agent reading only the spec should be able to implement without exploring the codebase. Self-contained means the WHAT is unambiguous — not that every type definition is embedded. Keep specs lean: if it's not needed to implement correctly, leave it out.

## Output

Save to `$TASK_DIR/SPEC.md`. Report back with a summary and your questions. **Stop here** — do not proceed to implementation.

## Session Capture

After writing the spec, append to `$TASK_DIR/SESSION.md`:

```
[TIME] crew-specwriter: drafted SPEC.md — <one-line goal from spec>
```
