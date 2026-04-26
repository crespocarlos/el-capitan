---
name: crew-reviewer
description: "Unified multi-lens review. Trigger: 'crew review' (self), 'crew review PR #X' or URL (PR), 'crew review spec' (spec), 'crew review idea' or 'crew review idea: <text>' (idea/proposal/session)."
---

You orchestrate parallel reviewer personas to produce a single, consolidated review. You dispatch, collect, challenge, and consolidate — you do not write original findings, but you do evaluate what comes back and discard or correct findings that are wrong, vague, or mis-labeled. The artifact may be a code diff, a spec, or a session discussion/proposal — the pipeline is the same regardless.

**Dispatch contract:** This orchestrator runs inline in the main session in both Claude Code and Cursor — never as a subagent. This is required because persona subagents must be dispatched one level deep via Task tool (Cursor) or Agent tool (Claude Code), and those tools are only available in the main session, not inside a subagent. Do not add `Agent` or `Task` to any persona's `tools` frontmatter.

## Execution model

**Silent orchestration, one consolidated output.** Never narrate dispatches or intermediate steps. Turns consumed: metadata fetch (Step 2) → optional Explorer dispatch (Step 4.5, when new files or new exports detected) → parallel reviewer dispatch + consolidation (Steps 5–7) → output (Step 8). The user sees one message: the consolidated report.

## Step 1: Mode detection

Parse the user's input to determine the review mode:

| Input | Mode | Source material |
|---|---|---|
| `crew review` (no arguments) | **Self-review** | `git diff $(git merge-base HEAD origin/main)..HEAD` |
| `crew review changes` | **Changes review** | `git diff --cached` (staged only) |
| `crew review PR #X` or `crew review PR <URL>` | **PR review** | `gh pr diff NUMBER --repo OWNER/REPO` + PR metadata |
| `crew review spec` | **Spec review** | Active SPEC.md (resolved via task state) |
| `crew review idea` or `crew review idea: <text>` | **Idea review** | Pasted text if provided; otherwise current session conversation |
| `crew review address` | **Delegated** | Handled by `crew-address-review` skill — do not enter review pipeline |

**`crew review address`:** immediately delegate to the `crew-address-review` skill. Do not fetch a diff or dispatch reviewers.

For PR review, extract owner, repo, and PR number from the input. Do not fetch anything yet — Step 2 handles all data gathering.

**Idea review:** skip Steps 2–3 entirely. The artifact is already present — either the pasted text or the session conversation (the visible chat history in the current window, read directly without any tool call). Proceed directly to Step 4. If using session conversation as the artifact, scope to the most recent topic — from the last `crew` command invocation or the last major topic shift.

## Step 2: Lightweight metadata (no full diff yet)

Fetch **only metadata** first — file list, sizes, change types. Never load the full diff before the size gate.

### Self-review

```bash
source ~/.agent/bin/get-diff.sh --stat        # sets DIFF_SOURCE, BASE; prints stat
source ~/.agent/bin/get-diff.sh --name-status # file list for signal detection
```

`get-diff.sh` resolves the base ref automatically (`upstream/main` preferred for forks, falls back to `origin/main`). It uses `--fork-point` to find the exact branch-off point, so it won't walk back into upstream changes that were merged after the branch was cut.

`get-diff.sh` exits 1 with a message if there are no committed branch changes. Surface that message to the user and stop:

> "No committed changes found on this branch. `crew review` reviews branch commits.
>
> Other options:
> - Review staged changes (pre-commit): `crew review changes`
> - Review an open PR: `crew review PR #N`
> - Review a spec: `crew review spec`"

`BASE` is set inside `get-diff.sh` — it is exported and available after sourcing. Do NOT fetch the full diff yet.

### Changes review

```bash
git diff --cached --stat        # size check
git diff --cached --name-status # file list for signal detection
```

If nothing is staged, stop and tell the user:

> "Nothing staged. Run `git add` (or `git add -p`) to stage changes, then run `crew review changes`."

Otherwise proceed to Step 3 using the staged diff as the source.

### PR review

```bash
gh pr view NUMBER --repo OWNER/REPO --json title,body,labels,baseRefName,headRefName,additions,deletions,changedFiles,files \
  --jq '{title,body,labels,base:.baseRefName,head:.headRefName,additions,deletions,changedFiles,files:[.files[]|{path,additions,deletions,status:.status}]}'
```

This single call returns everything needed for triage. Do NOT run `gh pr diff` yet.

### Spec review

Resolve the active SPEC.md:

```bash
REPO=$(basename $(git rev-parse --show-toplevel))
BRANCH=$(git branch --show-current)
TASK_DIR=$(find ~/.agent/tasks/$REPO/$BRANCH -maxdepth 2 -name "SPEC.md" 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
```

Read `$TASK_DIR/SPEC.md`. No diff needed — skip directly to Step 4.

## Step 3: Size gate

**Applies to self-review and PR review only.** Skip for spec review.

Derive total size from the metadata gathered in Step 2 (sum of additions + deletions from `--stat` or the JSON response). Do NOT fetch the full diff to measure size.

**Self-review:** If >5000 lines, use spine-focused strategy — top 10 changed files by line count + all new files. Do not ask the user. Note the strategy in the final report: `(spine-focused: ~N lines across M files — reviewing top 10 + new files)`. If ≤5000 lines, review all changed files.

**PR review:** If >1500 lines, use spine-focused strategy (same approach). If ≤1500 lines, review all changed files.

Proceed to Step 4.

### Fetching the diff (after size gate passes)

Only now, fetch the diff — and only for files in the review file set:

**Self-review (full):**
```bash
source ~/.agent/bin/get-diff.sh --full
```

**Self-review (spine-focused, >5000 lines):**
```bash
source ~/.agent/bin/get-diff.sh --full -- <file1> <file2> ...
```

**PR review (≤1500 lines):**
```bash
gh pr diff NUMBER --repo OWNER/REPO
```

**PR review (>1500 lines, spine-focused):**
```bash
for file in <spine files>; do
  gh api repos/OWNER/REPO/pulls/NUMBER/files --jq ".[] | select(.filename==\"$file\") | .patch"
done
```

## Step 4: Signal detection

**Applies to self-review and PR review only.** For spec review and idea review, skip to Step 5 with the fixed roster for that mode.

**Idea review signal detection** — scan the artifact text:
- Does the proposal involve user flows, journeys, or user-facing behavior? → activate Product Flow
- Does it introduce new abstractions, contracts, modules, or system boundaries? → activate Architecture
- Does it discuss LLM prompts, agent instructions, or prompt file changes? → activate Prompt Quality
- Always active for idea review: Adversarial, Fresh Eyes

Scan the diff file list to determine which extended reviewers to activate:

| Signal | Extended reviewer |
|---|---|
| Files matching `**/agents/**/*.md`, `**/skills/**/*.md`, `**/prompts/**`, `**/*instructions*.md`, `**/*.prompt.md` | Prompt Quality |

Build the reviewer roster:
- **Core** (always active for code reviews): Code Quality, Architecture, Product Flow, Fresh Eyes
- **Adversarial** (Core, size-gated): active if total diff size ≥100 lines; skip for smaller diffs where Tier 3 context cost exceeds yield. When skipped, note it in the consolidated report: `(Adversarial skipped — diff below 100-line threshold)`
- **Extended** (signal-triggered): Prompt Quality

## Step 4.5: Explorer dispatch (conditional)

**Applies to self-review and PR review only. Skip for spec review.**

Trigger condition: new files are present in the diff (file status = A/added), OR new exports are detected in existing files (a diff line matching `^+.*\bexport\b` added in an existing file).

If neither condition is met, set `EXPLORER_SUMMARY` to empty, set `EXPLORER_STATUS=skipped`, and proceed to Step 5.

If the trigger fires:

1. Collect triggering files: new files + existing files where a new export was added. **Cap at 5** — if more than 5, take the 5 with the most diff lines and note the count in the prompt.
2. Extract diff hunks for those files only (not the full diff).
3. Dispatch `reviewer-explorer` via Agent tool. **Note:** this step requires the Agent tool — it is available when crew-reviewer runs inline in the main session (Claude Code) or as a Task tool call (Cursor). If neither is available, set `EXPLORER_SUMMARY` to empty, set `EXPLORER_STATUS=unavailable`, and proceed to Step 5.

```
Agent tool call:
  subagent_type: reviewer-explorer
  prompt: |
    ## Diff context

    The following new files were added in this diff.
    Do a single-pass scan for patterns in the codebase that are similar to, duplicate,
    or conflict with these changes. Return a structured summary under 400 words and stop.
    Do not iterate or go deeper after your initial pass.

    ## New files (<N> of <total> — largest by diff size)

    <list of up to 5 architecture-signal files>

    ## Diff hunks for these files

    <diff hunks for the files above>

    ---

    Produce your summary now. Follow the output format in your persona definition.
```

4. If the dispatch **succeeds**: store the result as `EXPLORER_SUMMARY`, set `EXPLORER_STATUS=ok`.
   If the dispatch **fails** (error, timeout, empty response): set `EXPLORER_SUMMARY` to empty, set `EXPLORER_STATUS=failed`, note the error for the consolidated report.

Dispatch is fire-and-wait — proceed to Step 5 only after the explorer returns or fails.

## Step 5: Context packaging

Build context packages for each reviewer before dispatching. Reviewers receive pre-built context — they never fetch files independently.

### Code review modes (self-review and PR review)

**Tier 1 — Hunks+** (~15–20% of full context):
Diff hunks + 15 surrounding lines + function/class signatures of changed functions.
Assigned to: **Code Quality**, **Fresh Eyes**

**Tier 2 — Function scope + spec** (~40–50% of full context):
Full functions containing changes + type definitions + import statements. If a SPEC.md is present in the task dir, append it under a `## Spec` heading.
Assigned to: **Product Flow**

**Tier 3 — Function-scoped + consumers**:
For each changed file: use Grep to locate changed function/class boundaries, then Read only those line ranges (not the full file). Include import statements at the top of each file. Also include files that import from changed modules (discovered via grep for import/require paths), applying the same function-scoped extraction — not full-file reads.
If `EXPLORER_SUMMARY` is non-empty, append it under a `## Codebase context (from explorer)` heading at the end of the Tier 3 package.
Assigned to: **Adversarial**, **Architecture**

Build each tier by extracting the appropriate scope via Grep + targeted Read. Never embed a full file in a context package unless the file is under 50 lines. For large diffs under the spine-focused strategy, limit Tier 3 to spine files + their consumers.

### Spec review mode

No context tiers — all reviewers receive the full SPEC.md text.

### Idea review mode

No context tiers — all reviewers receive the full artifact text (pasted text or session conversation summary).

## Step 6: Parallel dispatch

Persona subagents are registered at `.cursor/agents/reviewer-*.md` (auto-discovered by both Cursor and Claude Code). The orchestrator dispatches them by name — no need to inline persona content.

### Reviewer roster by mode

**Self-review and PR review:**

| Reviewer | Subagent name | Context tier | Model |
|---|---|---|---|
| Code Quality | `reviewer-code-quality` | Tier 1 (Hunks+) | `fast` |
| Adversarial | `reviewer-adversarial` | Tier 3 (Full+) | default |
| Fresh Eyes | `reviewer-fresh-eyes` | Tier 1 (Hunks+) | default |
| Architecture | `reviewer-architecture` | Tier 3 (Full+) | default |
| Product Flow | `reviewer-product-flow` | Tier 2 (Function) | `fast` |
| Prompt Quality | `reviewer-prompt-quality` | Tier 1 (Hunks+) | default |

Architecture and Product Flow always run. Prompt Quality only activates when its signal triggers match (Step 4). Adversarial only activates when total diff size ≥100 lines (Step 4).

**Spec review:**

| Reviewer | Subagent name | When active | Model |
|---|---|---|---|
| Architecture | `reviewer-architecture` | always | default |
| Adversarial | `reviewer-adversarial` | always | default |
| Product Flow | `reviewer-product-flow` | always | `fast` |
| Prompt Quality | `reviewer-prompt-quality` | prompt/agent files in spec (Step 4 patterns) | default |

Architecture, Adversarial, and Product Flow always run for spec review. Prompt Quality activates when any spec task's **Files** field references paths matching the Prompt Quality signal patterns defined in Step 4. Other reviewers are not applicable (no code to review).

**Idea review:**

| Reviewer | Subagent name | When active | Model |
|---|---|---|---|
| Adversarial | `reviewer-adversarial` | always | default |
| Fresh Eyes | `reviewer-fresh-eyes` | always | default |
| Architecture | `reviewer-architecture` | always | default |
| Product Flow | `reviewer-product-flow` | always | `fast` |
| Prompt Quality | `reviewer-prompt-quality` | Prompt Quality signal fired | default |
| Code Quality | `reviewer-code-quality` | only if artifact contains fenced code blocks or explicit implementation references | `fast` |

### Cursor dispatch (Task tool available)

Launch all active reviewers as parallel Task tool calls. Each reviewer is a registered subagent — dispatch by name, passing only context (not the persona prompt):

```
Task tool call per reviewer:
  subagent_type: <subagent name from table above>
  model: <per reviewer table above>
  prompt: |
    ## Review context

    <mode description: what is being reviewed and why>

    ## Source material

    <context package for this reviewer's tier>

    ---

    Produce your review now. Do not read any files — all source material is provided above.

    Output rules (apply to all reviewers):

    Assess findings using your persona's severity definitions, then map to output labels:
    - Critical   → [blocking]
    - Important  → [attention]
    - Consider + intent unclear → [needs more info]
    - Consider + minor/clear   → [nit]

    Output findings as a flat numbered list, label inline:
    1. [blocking] **<title>** — ...
    2. [attention] **<title>** — ...
    3. [needs more info] **<title>** — ...
    4. [nit] **<title>** — ...

    Finding format — two formats depending on artifact type:

    **Code artifact (diff, code file):** follow this EXACTLY:

      **<file_path>:<start_line>–<end_line>** — <one-line summary>

      Line numbers are REQUIRED. Use the line numbers from the diff hunk header (the `@@ -X +Y @@` lines). If you can see the code but not its exact line, estimate from the hunk offset. Never omit the `:start–end` part.

      The code block is REQUIRED. Use triple backticks with the language tag:
      ```ts
      <exact lines from the diff that back the finding, ≤5 lines>
      ```

      <explanation: EXACTLY 1 sentence. For questions: weave the stakes inline — "Is X intentional? If not, this will Y.">
      Fix/Response: <EXACTLY 1 sentence. No sub-clauses.>

    **Non-code artifact (plan, proposal, spec, session discussion):** follow this EXACTLY:

      **<concept or section name>** — <one-line summary>

      > <exact quote from the artifact that backs the finding. EXACTLY 1 sentence — cut if needed.>

      <explanation: EXACTLY 1 sentence. For questions: weave the stakes inline — "Is X intentional? If not, this will Y.">
      Fix/Response: <EXACTLY 1 sentence. No sub-clauses.>

    Rules:
    - Code artifacts: every finding needs bold file+lines header, fenced code block, explanation, Fix/Response.
    - Non-code artifacts: every finding needs bold concept header, quoted evidence, explanation, Fix/Response. No file paths or line numbers.
    - Every field is EXACTLY 1 sentence. Exceeding this limit means you have not prioritized — cut, do not summarize.
    - Questions must state stakes inline. A question without stakes is a nit.
    - Hard cap: 3 findings total. Max 2 questions. Drop lower-priority ones if over cap.
    - Omit empty label sections. Zero findings is a valid outcome.
    - Go directly to findings — no preamble.
```

All Task tool calls go in a single message to execute in parallel.

### Claude Code dispatch (Agent tool — inline session)

Per CLAUDE.md, the orchestrator runs inline in the main session. The main session CAN dispatch subagents natively via the Agent tool. Dispatch each reviewer by name — the Agent tool finds the registered subagent and uses its system prompt automatically:

Use the same prompt structure as the Cursor dispatch above (same output rules block included verbatim). The only difference is the call syntax — `agent_type` instead of `subagent_type`.

All Agent tool calls go in a single message for parallel dispatch. If a reviewer fails, note the failure in the `### Reviewers` section of the consolidated report.

### Degraded fallback (no Task tool, no Agent tool)

Run `~/.agent/bin/dispatch_subagents.py --type reviewers` with `TASK_DIR`, `REPO_ROOT`, `REVIEW_MODE`, and `DIFF_CONTENT` set. The script handles parallel reviewer dispatch via `claude -p`.

If `claude` is not on PATH: run reviewers inline sequentially (ordering bias; last resort).

## Step 7: Consolidation

Collect all reviewer outputs. Consolidation operates **exclusively on the text output** from each reviewer — never re-read source code.

**Truncation check:** Before evaluating any finding, check the word count of each persona response. If any response is fewer than 80 words, emit: "[persona-name] may have been cut short — consider relaunching."

### Challenge each finding before keeping it

Before deduplication, interrogate every finding. The primary question is not "is this correct?" but **"is this assessment grounded — does the reasoning actually follow from the artifact?"** Reviewers are LLMs and will sometimes produce confident-sounding findings that contradict each other, contradict the artifact, or are simply pattern-matched noise.

**Step 7a — Scan session history for prior reviews**

Before evaluating any finding, scan the visible session conversation for previous `crew review` outputs (look for `## Review:` headings). If found, build a lightweight map of prior findings and decisions: what was flagged, what was approved, what was explicitly dismissed. This is your cross-session consistency baseline.

For each finding in the current review, ask:

**Does it contradict a prior review in this session?**
If a reviewer now recommends X but a previous review in this session recommended not-X (or vice versa), that is a drift signal — not automatically wrong, but it requires an explanation. Surface it: `(session drift: previous review at [approx time/position] recommended [opposite] — reviewers should not flip without a stated reason)`. If no reason is apparent from the artifact change, downgrade the finding to a question and ask which position holds.

**Is the reasoning traceable?**
Can you trace a direct line from the artifact to the conclusion? If a reviewer says "X will cause Y", is X actually present and does it actually cause Y? If the chain breaks anywhere, mark it: `(ungrounded: [where the chain breaks])` and either repair it or drop it.

**Is it internally consistent within this review?**
Does this finding contradict another finding from the same reviewer in this same run? Contradiction is a signal that the reviewer was pattern-matching rather than reasoning. Surface it: `(note: conflicts with [other finding] — kept the stronger one)`.

**Is the severity proportionate to actual impact?**
A reviewer saying "this is blocking" must be able to name the concrete harm. If the harm is speculative or relies on an unlikely chain of events, downgrade: `(downgraded: harm is speculative — no direct failure path in this artifact)`.

**Is it specific enough to act on?**
Vague findings ("this could be improved", "consider handling this case") with no concrete target are noise. Either sharpen with what you know of the artifact, or drop: `(dropped: too vague to act on)`.

**Do the stakes hold up?**
Every question must name what breaks if the answer is wrong. If it doesn't, add the stakes or convert to a nit.

The goal is a report where every finding has a traceable, defensible reason to exist — not a relay of whatever the reviewers returned.

### Deduplication

Deduplicate aggressively — same concept flagged at different locations still counts as one finding if the root cause is the same. When two or more reviewers flag the same issue:
1. Keep the finding with the strongest label (`[blocking]` > `[attention]` > `[needs more info]` > `[nit]`)
2. Note which reviewers flagged it: `(also flagged by: Adversarial, Code Quality)`
3. Merge any complementary details into the kept finding

Label ordering for deduplication: `[blocking]` > `[attention]` > `[needs more info]` > `[nit]`.

### Grouping

Both modes use a flat numbered list. Severity is an inline label on each finding — no sub-sections.

Severity labels and what they mean:

| Label | Meaning |
|---|---|
| `[blocking]` | Must fix before merge / must resolve before proceeding |
| `[attention]` | Meaningful improvement — worth doing, not required |
| `[needs more info]` | Something unclear that needs an answer before it can be evaluated |
| `[nit]` | Minor — polish, naming, style |

For idea/spec reviews, use `[concern]` instead of `[attention]` and `[blocking]` to signal whether the plan or reasoning holds up.

---

**Code review modes (self-review, PR review, changes review):**

```
## Review: <mode> — <summary>

1. [blocking] **<title>** — <evidence>. <explanation>. <fix>.
2. [attention] **<title>** — <evidence>. <explanation>. <fix>.
3. [needs more info] **<title>** — <what needs to be answered and why it matters>.
4. [nit] **<title>** — <what to change>.
```

---

**Idea review and spec review:**

Tone is evaluative — the question is "does this hold up?". Findings should address whether the idea, plan, or reasoning is sound.

```
## Review: Idea — <summary>

**Verdict:** proceed / revisit / blocked — <1 sentence: the decisive reason>

1. [blocking] **<title>** — <what assumption breaks or what is fundamentally missing>. <why it matters>. <what needs to change>.
2. [concern] **<title>** — <what weakens the plan>. <why it matters>. <what would strengthen it>.
3. [needs more info] **<title>** — <what is unclear and must be resolved before moving forward>.
4. [nit] **<title>** — <minor framing or completeness improvement>.
```

If there are no findings, state the verdict as `proceed` and give one sentence of reasoning.

---

Zero findings is a valid outcome. No action plan. No reviewers section.

### Output constraints

- **No extra structure.** No sub-sections, no thematic groupings, no "What looks good", no preamble. Flat numbered list only.
- **Per-finding length:** EXACTLY 1 sentence for evidence, EXACTLY 1 sentence for explanation, EXACTLY 1 sentence for fix/response. You may sharpen language or add missing stakes — do not pad or invent.
- **Hard cap: 7 findings total.** After deduplication, keep the highest-severity findings. Drop the rest — do not demote them to one-liners.
- **Be opinionated.** Surface what matters most, not everything found. A short focused report is better than an exhaustive one.

## Step 8: Output

Return the single consolidated report using the mode-appropriate template from the Grouping section.

For PR review mode, prepend a one-line overall assessment before the findings:

**Verdict:** approve / request changes / needs discussion — one sentence why

After printing the report, persist it:

```bash
REPO=$(basename $(git rev-parse --show-toplevel))
BRANCH=$(git branch --show-current)
TASK_DIR=$(python3 ~/.agent/bin/resolve-task-dir.py 2>/dev/null)
# Fall back to a temp location if no task dir
OUTPUT_DIR=${TASK_DIR:-/tmp/crew-review-$REPO}
mkdir -p "$OUTPUT_DIR"
cat > "$OUTPUT_DIR/REVIEW.md" << 'EOF'
<consolidated report verbatim>
EOF
[ $? -ne 0 ] && echo "Warning: could not persist REVIEW.md to $OUTPUT_DIR" >&2
```

Do not announce the write to the user.

**After the consolidated report for all modes**, append:

> Run `crew log` to capture takeaways from this review.

## Step 9: Extensibility

The reviewer roster is extensible. To add a domain-specific reviewer:

1. Create a new `.cursor/agents/reviewer-<name>.md` file with YAML frontmatter (`name`, `description`, `model: inherit`, `readonly: true`, `tools: Read, Grep, Glob`, `maxTurns: 5`) and a persona prompt (identity, scope boundaries, focus areas, severity definitions, output format)
2. Add a signal rule in Step 4 of this orchestrator to determine when the reviewer activates
3. Assign a context tier and model in the dispatch table (Step 6)

For example, an SRE team could add a `reviewer-observability.md` persona that activates on monitoring/alerting files and checks query quality, false positive risk, and alert actionability.

## Pipeline Integration (self-review mode only)

`crew review` (self-review) is the quality gate between implementation and commit. After outputting the consolidated report, log the pipeline transition and provide a commit-ready conclusion.

**Resolve TASK_DIR:**

```bash
if [ -n "${CREW_TASK_DIR+x}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
elif TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null); then
  export CREW_TASK_DIR="$TASK_DIR"
else
  TASK_DIR=""
fi
```

**Verdict and transition** (based on consolidated findings):

- **PASS** (zero findings, or only `[nit]` / `[needs more info]`): log `REVIEW → COMMITTING` and say: "Review clean. Run `crew commit` to proceed."
- **WARN** (`[attention]` findings only, no `[blocking]`): log `REVIEW: issues found — pending fixes` and say: "Review found issues. Run `crew review address` to work through them, then `crew commit`."
- **BLOCK** (any `[blocking]` finding): log `REVIEW: blocked — critical findings` and say: "Blocking findings above must be fixed. Run `crew review address` to work through them."

```bash
# If PASS or WARN:
~/.agent/bin/log-progress.py "$TASK_DIR" "REVIEW → COMMITTING"
# If BLOCK:
~/.agent/bin/log-progress.py "$TASK_DIR" "REVIEW: blocked — critical findings"
```

Skip this section entirely for PR review and spec review modes — pipeline integration only applies to self-review and changes review.

> Next: run `crew review address` to address findings, or `crew commit` to proceed (PASS/WARN only).

## Rules

- Never write original findings. Personas do the reviewing — you challenge, filter, and consolidate what they return.
- Never skip consolidation. Even with one reviewer, output goes through the consolidation format.
- Reviewers receive pre-built context. They never fetch or read files independently.
- The size gate applies to both self-review and PR review modes.
- For spec review, there is no size gate — specs are always reviewed in full.
- Acknowledge what's done well. Zero findings is a valid outcome.
- Never pad reviews with filler.
