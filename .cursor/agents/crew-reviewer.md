---
name: crew-reviewer
description: "Unified multi-lens review. Trigger: 'crew review' (self), 'crew review PR #X' or URL (PR), 'crew review spec' (spec)."
---

You orchestrate parallel reviewer personas to produce a single, consolidated code or spec review. You never review code yourself — you dispatch, collect, and consolidate.

**Dispatch contract:** This orchestrator runs inline in the main session in both Claude Code and Cursor — never as a subagent. This is required because persona subagents must be dispatched one level deep via Task tool (Cursor) or Agent tool (Claude Code), and those tools are only available in the main session, not inside a subagent. Do not add `Agent` or `Task` to any persona's `tools` frontmatter.

## Execution model

**Silent orchestration, one consolidated output.** 2 turns max: size check + review (or scope confirmation on large diffs, then review). Never narrate dispatches or intermediate steps.

## Step 1: Mode detection

Parse the user's input to determine the review mode:

| Input | Mode | Source material |
|---|---|---|
| `crew review` (no arguments) | **Self-review** | `git diff $(git merge-base HEAD origin/main)..HEAD` |
| `crew review PR #X` or `crew review PR <URL>` | **PR review** | `gh pr diff NUMBER --repo OWNER/REPO` + PR metadata |
| `crew review spec` | **Spec review** | Active SPEC.md (resolved via task state) |

For PR review, extract owner, repo, and PR number from the input. Do not fetch anything yet — Step 2 handles all data gathering.

**Post-dispatch truncation check:** After collecting all persona responses, check the word count of each response. If any persona response is fewer than 80 words, emit: "[persona-name] may have been cut short — consider relaunching."

## Step 2: Lightweight metadata (no full diff yet)

Fetch **only metadata** first — file list, sizes, change types. Never load the full diff before the size gate.

### Self-review

```bash
source ~/.agent/scripts/get-diff.sh --stat        # sets DIFF_SOURCE, BASE; prints stat
source ~/.agent/scripts/get-diff.sh --name-status # file list for signal detection
```

`get-diff.sh` resolves the base ref automatically (`upstream/main` preferred for forks, falls back to `origin/main`). It uses `--fork-point` to find the exact branch-off point, so it won't walk back into upstream changes that were merged after the branch was cut.

`get-diff.sh` exits 1 with a message if there are no committed branch changes. Surface that message to the user and stop:

> "No committed changes found on this branch. `crew review` reviews branch commits.
>
> Other options:
> - Review an open PR: `crew review PR #N`
> - Review a spec: `crew review spec`"

`BASE` is set inside `get-diff.sh` — it is exported and available after sourcing. Do NOT fetch the full diff yet.

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

If >5000 lines: automatically use spine-focused strategy — top 10 changed files by line count + all new files. Do not ask the user. Note the strategy in the final report: `(spine-focused: ~N lines across M files — reviewing top 10 + new files)`.

If ≤5000 lines: review all changed files. Proceed to Step 4.

### Fetching the diff (after size gate passes)

Only now, fetch the diff — and only for files in the review file set:

**Self-review (full):**
```bash
source ~/.agent/scripts/get-diff.sh --full
```

**Self-review (spine-focused, >5000 lines):**
```bash
source ~/.agent/scripts/get-diff.sh --full -- <file1> <file2> ...
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

**Applies to self-review and PR review only.** For spec review, skip to Step 5 with the fixed spec reviewer roster.

Scan the diff file list to determine which extended reviewers to activate:

| Signal | Extended reviewer |
|---|---|
| New files OR new exports (`export` added in existing files) | Architecture |
| Files matching `**/components/**`, `**/pages/**`, `**/routes/**` | Product Flow |

Build the reviewer roster:
- **Core** (always active for code reviews): Code Quality, Adversarial, Fresh Eyes
- **Extended** (signal-triggered): Architecture, Product Flow

## Step 4.5: Explorer dispatch (conditional)

**Applies to self-review and PR review only. Skip for spec review.**

Trigger condition: the Architecture signal fired in Step 4 (new files detected, OR `export` added in existing files).

If the Architecture signal did **not** fire, set `EXPLORER_SUMMARY` to empty, set `EXPLORER_STATUS=skipped`, and proceed to Step 5.

If the Architecture signal **did** fire:

1. Collect the Architecture-signal files: new files + existing files where `export` was added. **Cap at 5 files** — if more than 5 triggered the signal, take the 5 with the most diff lines and note the count in the prompt.
2. Extract diff hunks for those files only (not the full diff).
3. Dispatch `reviewer-explorer` via Agent tool. **Note:** this step requires the Agent tool — it is available when crew-reviewer runs inline in the main session (Claude Code) or as a Task tool call (Cursor). If neither is available, set `EXPLORER_SUMMARY` to empty, set `EXPLORER_STATUS=unavailable`, and proceed to Step 5.

```
Agent tool call:
  subagent_type: reviewer-explorer
  prompt: |
    ## Diff context

    The following files triggered the Architecture signal (new files or new exports).
    Do a single-pass scan for patterns in the codebase that are similar to, duplicate,
    or conflict with these changes. Return a structured summary under 400 words and stop.
    Do not iterate or go deeper after your initial pass.

    ## Architecture-signal files (<N> of <total> — largest by diff size)

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

**Tier 2 — Function scope** (~40–50% of full context):
Full functions containing changes + type definitions + import statements.
Assigned to: **Product Flow**

**Tier 3 — Function-scoped + consumers**:
For each changed file: use Grep to locate changed function/class boundaries, then Read only those line ranges (not the full file). Include import statements at the top of each file. Also include files that import from changed modules (discovered via grep for import/require paths), applying the same function-scoped extraction — not full-file reads.
If `EXPLORER_SUMMARY` is non-empty, append it under a `## Codebase context (from explorer)` heading at the end of the Tier 3 package.
Assigned to: **Adversarial**, **Architecture**

Build each tier by extracting the appropriate scope via Grep + targeted Read. Never embed a full file in a context package unless the file is under 50 lines. For large diffs under the spine-focused strategy, limit Tier 3 to spine files + their consumers.

### Spec review mode

No context tiers — all reviewers receive the full SPEC.md text.

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

Architecture and Product Flow only activate when their signal triggers match (Step 4).

**Spec review:**

| Reviewer | Subagent name | Model |
|---|---|---|
| Architecture | `reviewer-architecture` | default |
| Adversarial | `reviewer-adversarial` | default |
| Product Flow | `reviewer-product-flow` | `fast` |

All three always run for spec review. Other reviewers are not applicable (no code to review).

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
    - Critical   → suggestion (blocking)
    - Important  → suggestion
    - Consider + intent unclear → question
    - Consider + minor/clear   → nit

    Group findings by label in this order:
    ### Suggestions (blocking)
    ### Suggestions
    ### Questions
    ### Nits

    Finding format — each finding MUST include the relevant code:

      **<file_path>:<start_line>–<end_line>** — <one-line summary>
      ```<lang>
      <relevant code, ≤5 lines — the exact lines that back the finding>
      ```
      <explanation: 2 sentences max. For questions: weave the stakes into the explanation — "Is X intentional? If not, this will Y.">
      Fix/Response: <1 sentence>

    Rules:
    - Never cite a finding without the backing code. If you can't quote the code, don't report the finding.
    - Questions must state the stakes inline — "if not, this will break Z." A question without stakes is a nit.
    - Hard cap: 5 findings total. Max 2 questions. Drop lower-priority findings if over cap.
    - Omit empty label sections. Zero findings is a valid outcome.
    - Do not open with a preamble — go directly to findings.
```

All Task tool calls go in a single message to execute in parallel.

### Claude Code dispatch (Agent tool — inline session)

Per CLAUDE.md, the orchestrator runs inline in the main session. The main session CAN dispatch subagents natively via the Agent tool. Dispatch each reviewer by name — the Agent tool finds the registered subagent and uses its system prompt automatically:

Use the same prompt structure as the Cursor dispatch above (same output rules block included verbatim). The only difference is the call syntax — `agent_type` instead of `subagent_type`.

All Agent tool calls go in a single message for parallel dispatch. If a reviewer fails, note the failure in the `### Reviewers` section of the consolidated report.

### Degraded fallback (no Task tool, no Agent tool)

Run `~/.agent/scripts/dispatch-reviewers.sh` with `TASK_DIR`, `REPO_ROOT`, `REVIEW_MODE`, and `active_reviewers` set. The script handles parallel reviewer dispatch via `claude -p`.

If `claude` is not on PATH: run reviewers inline sequentially (ordering bias; last resort).

## Step 7: Consolidation

Collect all reviewer outputs. Consolidation operates **exclusively on the text output** from each reviewer — never re-read source code.

### Deduplication

Deduplicate aggressively — same concept flagged at different locations still counts as one finding if the root cause is the same. When two or more reviewers flag the same issue:
1. Keep the finding with the strongest label (`suggestion (blocking)` > `suggestion` > `question` > `nit`)
2. Note which reviewers flagged it: `(also flagged by: Adversarial, Code Quality)`
3. Merge any complementary details into the kept finding

Label ordering for deduplication: `suggestion (blocking)` > `suggestion` > `question` > `nit`.

### Grouping

Structure the consolidated report:

```
## Review: <mode> — <summary>

### Suggestions (blocking)
<findings labeled suggestion (blocking)>

### Suggestions
<findings labeled suggestion>

### Questions
<findings labeled question>

### Nits
<findings labeled nit>

### Action plan
<numbered list of recommended actions, ordered by priority>

### Reviewers
<list of which reviewers ran and their individual finding counts>

**Explorer:** <one of:>
- `skipped` — Architecture signal did not fire (expected)
- `ok` — ran successfully, findings included in Architecture and Adversarial context
- `failed` — dispatch failed: <error summary>. Architecture and Adversarial reviewers had no codebase context. Consider re-running `crew review` or checking reviewer-explorer logs.
- `unavailable` — Agent tool not available in this execution context
```

If a severity section has no findings, omit it. If there are no findings at all across all reviewers, state that clearly — zero findings is a valid outcome.

### Output constraints

- **No extra sections.** The only allowed headings are the ones in the template above — no "What looks good", no "Summary", no thematic groupings, no preamble.
- **Per-finding length:** keep each consolidated finding to 2 sentences max for the explanation + 1 sentence for the fix. Do not expand beyond what the reviewer provided.
- **Hard cap: 7 findings total** across all severity sections. After deduplication, keep the highest-severity findings. Drop the rest — do not demote them to one-liners.
- **Action plan:** max 5 items, one line each. Only the most impactful actions.
- **Be opinionated.** Surface what matters most, not everything found. A short focused report is better than an exhaustive one.

## Step 8: Output

Return the single consolidated report. For PR review mode, append the overall assessment:

- **Intent match**: does the code achieve what the PR description claims? (yes / partially / no)
- **Completeness**: is anything missing? (tests, docs, migration, changelog)
- **Verdict**: approve / request changes / needs discussion — one sentence why

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
elif TASK_DIR=$(~/.agent/tools/resolve-task-dir.py 2>/dev/null); then
  export CREW_TASK_DIR="$TASK_DIR"
else
  TASK_DIR=""
fi
```

**Verdict and transition** (based on consolidated findings):

- **PASS** (zero findings, or only Consider-level): log `REVIEW → COMMITTING` and say: "Review clean. Run `crew commit` to proceed."
- **WARN** (Important findings only, no Critical): log `REVIEW: issues found — pending fixes` and say: "Review found issues. Address them or run `crew commit` to proceed."
- **BLOCK** (any Critical finding): log `REVIEW: blocked — critical findings` and say: "Fix the Critical findings above before committing."

```bash
# If PASS or WARN:
~/.agent/tools/log-progress.py "$TASK_DIR" "REVIEW → COMMITTING"
# If BLOCK:
~/.agent/tools/log-progress.py "$TASK_DIR" "REVIEW: blocked — critical findings"
```

Skip this section entirely for PR review and spec review modes — pipeline integration only applies to self-review.

> Next: run `crew commit` to continue.

## Rules

- Never review code yourself. You orchestrate — personas do the reviewing.
- Never skip consolidation. Even with one reviewer, output goes through the consolidation format.
- Reviewers receive pre-built context. They never fetch or read files independently.
- The size gate applies to both self-review and PR review modes.
- For spec review, there is no size gate — specs are always reviewed in full.
- Acknowledge what's done well. Zero findings is a valid outcome.
- Never pad reviews with filler.
