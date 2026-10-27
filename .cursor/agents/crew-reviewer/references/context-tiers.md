## Step 5: Context packaging

Build context packages for each reviewer before dispatching. Reviewers receive pre-built context first and should prefer it. They may do up to **8 targeted fetch calls** (Grep + Read + SemanticCodeSearch combined) to ground a finding they cannot verify from the provided context alone — but they must not re-read files already included in their package.

### Code review modes (self-review, changes review, and PR review)

**Tier 1 — Hunks+** (~15–20% of full context):
Diff hunks + 15 surrounding lines + function/class signatures of changed functions.
Assigned to: **Code Quality**, **Fresh Eyes**

**Tier 2 — Function scope + spec** (~40–50% of full context):
Full functions containing changes + type definitions + import statements. If a SPEC.md is present in the task dir, append it under a `## Spec` heading.
For PR review, append a compact `## PR contract` section containing the PR description, linked ticket titles/bodies, acceptance criteria, base/head SHAs, and explicit non-goals. Product Flow must check every acceptance criterion; Architecture and Code Quality should use the section to detect contract and implementation contradictions.
Assigned to: **Product Flow** (and the contract summary to all reviewers)

**Tier 3 — Function-scoped + consumers**:
For each changed file: use Grep to locate changed function/class boundaries, then Read only those line ranges (not the full file). Include import statements at the top of each file. Also include files that import from changed modules (discovered via grep for import/require paths), applying the same function-scoped extraction — not full-file reads.
If `EXPLORER_SUMMARY` is non-empty, append it under a `## Codebase context (from explorer)` heading at the end of the Tier 3 package.
Assigned to: **Adversarial**, **Architecture**

**Prompt tier — full prompt + direct contract context**:
For each changed prompt, instruction, skill, or agent file, include the complete changed file rather than only hunks. Include directly referenced prompts, skills, tools, evaluators, and model/runtime configuration when they can be identified from imports, links, or nearby paths. Include relevant failing examples or acceptance criteria when provided. Do not include unrelated repository files.
Assigned to: **Prompt Quality**

Build each tier by extracting the appropriate scope via Grep + targeted Read. For non-prompt tiers, never embed a full file in a context package unless the file is under 50 lines. Prompt files are the explicit exception above. For large diffs under the spine-focused strategy, limit Tier 3 to spine files + their consumers.

### Spec review mode

No context tiers — all reviewers receive the full SPEC.md text.

### Idea review mode

No context tiers — all reviewers receive the full artifact text (pasted text or session conversation summary).

## Repo memory

Before dispatch, call `mem.py context --mode review --paths <changed files>` once. Append its output under `## Repo memory` in every context package. On exit 2, append `warning: memory unavailable`.
