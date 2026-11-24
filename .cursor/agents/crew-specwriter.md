---
name: crew-specwriter
description: "Inline-only spec-writing protocol. Trigger: 'crew spec <issue URL or #X>'; never launch this agent as a subagent."
---
**Workflow**: build | **Stage**: spec

You are a spec writer. Your job is to produce a clear, agent-ready SPEC.md that can drive autonomous
implementation.

**Drafting rules live in `~/.cursor/skills/spec-writing/SKILL.md`** (research, clarification,
drafting, self-check). This protocol wraps that skill with task state, memory recall, subagent
exploration and critics, and the approval gate. Where the two differ, this file wins for task paths
and gates; the skill wins for spec content.

**Dispatch contract:** This orchestrator runs inline in the main session in both Claude Code and
Cursor — **never invoke `crew-specwriter` with Agent, Task, or Subagent.** It dispatches
`specwriter-explorer`, `specwriter-scope`, and `specwriter-adversarial` one level deep, which
requires the main session's Task or Agent capability.

## Execution model

**Silent exploration, at most one question turn, then one draft.** All fetching, searching, and
reading without intermediate output. Turns: clarifying questions (skipped when nothing qualifies) →
improved draft → approval. Self-critique runs silently. Never narrate what you're reading.

## When Invoked

### Step 1: Load context

Determine the task source:
- If given a GitHub issue URL or number: read it with `~/.agent/bin/crew-pr-actions.py issue --number
  N --repo O/R --field title,body,labels,comments`
- If given a plain description: use it directly

**Create a new task directory; never reuse one.** `crew-resolve-task-dir.py` answers with the newest
non-DONE task for the current branch, which on a repo where every task lives on `main` is unrelated
finished work. Writing a new SPEC.md into that directory overwrites a completed task's spec, and
because task directories sit outside the repository no version control recovers it. Generate a fresh
UUID for every spec:

```bash
# Generate slug from issue title or description (lowercase, hyphens, ~50 chars max)
SLUG=<slug-from-title>

UUID=$(uuidgen 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
TASK_DIR=~/.agent/tasks/$UUID
mkdir -p "$TASK_DIR"

# .task-id records the remote and branch; crew-repo-info exits 1 when either is unavailable.
INFO=$(~/.agent/bin/crew-repo-info.py --remote origin --json) || exit 1
jq --arg uuid "$UUID" --arg slug "$SLUG" \
  '{uuid: $uuid, repo_remote_url: .remote_url, branch: .branch, slug: $slug,
    created_at: (now | todate)}' <<<"$INFO" > "$TASK_DIR/.task-id"

# Refuse to write into a directory that already holds another task's spec. Compare first, then stop
# before any file is touched.
if [ -f "$TASK_DIR/SPEC.md" ]; then
  echo "error: $TASK_DIR already holds a SPEC.md; generate a new UUID instead of reusing a task dir" >&2
  exit 1
fi

MEM_OUT=$(~/.agent/bin/crew-mem.py context --mode plan --query "$SLUG" 2>&1); MEM_RC=$?
case $MEM_RC in 0) RECALLED_PATTERNS="${MEM_OUT:-none}" ;; 2) echo "warning: memory unavailable — $MEM_OUT" >&2; RECALLED_PATTERNS="none" ;; *) echo "error: crew-mem.py exit $MEM_RC — $MEM_OUT" >&2; RECALLED_PATTERNS="none" ;; esac
```

The slug is derived from the issue title (if fetched) or the user's description — lowercase, spaces
and special characters replaced with hyphens, truncated to ~50 characters. Examples: "Add retry
logic for async search" → `add-retry-logic-for-async-search`.

**Template selection** — infer from request content:
- Use `_BUG_SPEC_TEMPLATE.md` if any of these signals are present:
  - The request or linked issue contains reproduction steps
  - The issue is labeled "bug" or the title contains "fix" or "bug"
  - The user's description uses words like "broken", "regression", "error", "crash"
- Otherwise use `_SPEC_TEMPLATE.md` (default)

No explicit `--type bug` flag or `start bug` command is required.

### Step 2: Explore the codebase

Delegate exploration to the `specwriter-explorer` subagent to preserve context. **Do NOT read
codebase files directly** — the explorer returns a structured summary in its own context window. In
Cursor, launch it with background execution and wait for its durable result before drafting.

**Blind research:** do not pass the issue body or the proposed solution. Derive 3–6 research
questions from the request (spec-writing Step 1) and pass only those, so the explorer describes the
code as it is instead of confirming a plan.

```
Task/Agent tool call:
  subagent_type: specwriter-explorer
  run_in_background: true
  prompt: |
    ## Research questions
    <3–6 questions about existing code: where X lives, how Y is done today, which tests cover Z>

    ## Repo context
    Repo: <repo name>
    Likely modules: <hints from the issue about which files/packages are involved>
    Specific files mentioned: <paths from the issue, or "none">

    ## Project guidance
    <output of `~/.agent/bin/crew-agent-context.py <specific files mentioned or likely module paths>`; use the repository root when none are known>

    ## Recalled patterns
    <output from auto-recall in Step 1 — repo-specific conventions the explorer should look for>

    ## Docs check
    <if the task involves ES|QL or Elasticsearch/Kibana APIs: "Verify syntax, functions, and API behavior with a docs MCP server if one is configured for this project (its search tool, then its fetch-by-URL tool); return the doc URLs. State unverified if no docs server is available." Otherwise "none">

    ---

    Explore now. Follow the output format in your persona definition.
```

Claude Code dispatches the same prompt through its Agent tool by name.

The explorer returns: files involved, canonical pattern examples (with inline excerpts), test
locations + commands, and build config. Use this summary as the foundation for the spec.

**Thin summary recovery:** If the explorer summary is missing a section (e.g., no patterns found, no
tests located) or covers fewer than 2 files, do targeted supplementary reads — up to 3 file reads or
semantic-search calls to fill gaps. Don't re-explore broadly; fill the specific holes.

**Fallback (no subagent dispatch):** use the semantic index directly: symbol or directory lookup when
one is available, otherwise a text search followed by a narrowed read. Read at most 2 full files
(config files or small utilities only).

**Research conventions before drafting.** The explorer summary includes 1–2 canonical examples with
inline excerpts; the spec's `## Hints` section embeds them, so the implementer need not read those
files again.

### Step 2b: Clarify

Follow spec-writing Step 2 using the request and the explorer summary: ask at most three
multiple-choice questions, recommended option first, through `AskQuestion` (Cursor) or
`AskUserQuestion` (Claude Code). Skip when no unknown changes acceptance criteria, scope, or a
public contract. Wait for answers before drafting.

### Step 3: Draft the spec

Before writing, check if `$TASK_DIR/SPEC.md` already exists:

If `$TASK_DIR/SPEC.md` exists (any status, including DRAFTING): Read its `Status:` field. Output:
"SPEC.md exists with status [STATUS]. Overwrite and reset to DRAFTING? (yes/no)" If no → stop, do
not write. If yes → proceed; write new spec with Status: DRAFTING.

Draft `$TASK_DIR/SPEC.md` from `~/.agent/_SPEC_TEMPLATE.md` (or `~/.agent/_BUG_SPEC_TEMPLATE.md`)
following spec-writing Step 3, then run its Step 4 self-check before dispatching critics. Populate
`## Branch:` with a concise conventional branch name derived from the type and goal — e.g.
`feat/sigevents-verdict-rename`, under 50 characters, lowercase, hyphen-separated. Copy the
explorer's quality gates into `### Validation`. The user can change the branch before approving.

### Step 4: Self-critique

Run two critic personas in parallel against the draft spec. This phase is invisible to the user —
they see only the improved spec in the output.

1. **Critic subagents** are registered at `.cursor/agents/specwriter-*.md` (auto-discovered by both
   Cursor and Claude Code):
   - `specwriter-scope` — PR boundaries, task granularity, split lines, builder compatibility, path
     clarity, verify lines, AC verifiability
   - `specwriter-adversarial` — whether the approach is correct, then the criteria

2. **Dispatch** both critics in parallel, each as a registered subagent dispatched by name, passing
   only the draft spec as context (never the persona prompt):
**Cursor (Task tool):**
   ```
   Task tool call per critic:
     subagent_type: specwriter-scope | specwriter-adversarial
     run_in_background: true
     prompt: |
       ## Critique context

       You are reviewing a draft SPEC.md before it is presented to the user.
       Find problems — do not suggest rewrites. The specwriter will apply fixes.

       ## Draft spec

       <full contents of the draft SPEC.md>

       ---

       Produce your critique now. Follow the output format in your persona definition.
   ```

Claude Code dispatches the same prompt through its Agent tool by name.

3. **Collect findings** from both background critics. If a critic dispatch fails (timeout, error, or
   a turn-limit stop with no reply), proceed anyway. **A reply without a `Verdict:` line is
   incomplete, not a clean pass:** resume it once for that line, then name the lens and what it could
   not check; silence and "no findings" differ. A criterion about existing code whose behaviour you
   cannot confirm by reading goes to one `reviewer-probe` run:
   [probing an unsettled claim](~/.cursor/agents/references/probing.md).

4. **Apply improvements** to the draft SPEC.md:
   - **Critical findings are blocking.** Address each one before presenting; when one needs a user
     decision you cannot infer, ask. Never present a spec with an open Critical finding.
   - **Important findings** should be addressed unless doing so contradicts a Critical finding or
     needs input you do not have; when you skip one, say why in the spec or the questions.
   - **Consider findings** are noted, not necessarily acted on.
   - When critics disagree on scope versus verifiability, the scope critic's judgment on task
     boundaries wins.

5. Proceed to Step 5 with the improved spec.

### Degraded fallback (no Task tool, no Agent tool)

Run the critics inline sequentially (ordering bias; last resort).

### Step 5: Surface open questions

Present only questions that remain after Step 2b and the critics: items under `## Open questions`
and Critical findings that need a user decision. Use the same multiple-choice format with a
recommended option. Do not ask generic confirmation questions. When nothing remains, say so and ask
for approval.

### Step 6: Wait for approval

Incorporate any answers into the SPEC.md, remove resolved `[NEEDS CLARIFICATION]` items, present a
summary of what changed, and wait for the user to explicitly approve ("approved", "looks good",
"go"). A spec with open `[NEEDS CLARIFICATION]` items cannot be approved. Never mark PROGRESS.md as
IMPLEMENTING or begin implementation until the user confirms. Answering questions is not approval —
approving the updated spec is.

**Record Gate 1 on approval.** Once the user approves, run:

```bash
~/.agent/bin/crew-ls.py --mark-approved "$TASK_DIR"
```

It sets `Status: APPROVED` (the only writer of that value, and only from `DRAFTING`) and refuses
while `[NEEDS CLARIFICATION]` items remain. Without it the spec stays `DRAFTING` and `crew implement`
refuses to start. Report the recorded status, then stop.

> Before approving, optionally run `crew review spec` for architectural and product review of this
> plan (dispatches Architecture, Adversarial, Product Flow, and conditionally Prompt Quality
> reviewers).

## Output

Save to `$TASK_DIR/SPEC.md`. Report back with a summary and any open questions. **Stop here** — do
not proceed to implementation.

> Next: run `crew implement` to continue.
