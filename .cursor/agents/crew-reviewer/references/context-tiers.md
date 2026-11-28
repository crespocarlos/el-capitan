## Step 5: Context packaging

Inputs from `crew-reviewer`: `REVIEW_ROOT` (the review directory) and `TASK_DIR` (the task, empty
for none).

Build context packages for each reviewer before dispatching. Reviewers receive pre-built context
first and should prefer it. They may do up to **8 targeted fetch calls** (repository search and
targeted file reads, by whatever name the harness exposes them) to ground a finding they cannot
verify from the provided context alone, without re-reading files already in their package.

**Every package states its output contract, including the hunk requirement.** The shared reviewer
contract carries the hunk-citation rule, but a package assembles the rule's *inputs*: without the
`## Hunk reference` section below, a persona has no ids to cite. Restate the sentence verbatim
directly under that heading, so the ids the persona cites are the ids in front of it; without it,
personas cite none and strict persistence fails every `[blocking]`/`[attention]` finding for a reason
the persona was never told:

> Every `[blocking]` and `[attention]` finding cites the hunk ids whose change causes it, next to the
> `file:line` anchor: `[attention] src/a.ts:42 (h7) — …`, or `(h3, h7)`. A finding no hunk causes is
> pre-existing; say so instead of citing a hunk that does not cause it.

Also state the review mode in the same preamble (self, changes, PR, spec, or idea), so a persona
applies the contract's label row for that mode (`[concern]` in a spec or idea review).

### Self and changes review modes

The size gate (see "Spine files" below) decides which of two packaging strategies applies. It is
checked first, and the two never both apply:

- **At or above the threshold** — spine strategy: spine files and their consumers only.
- **Below the threshold** — the complete diff (`package.diff`, generated files collapsed) is the
  hunk source for every persona; do not re-extract what it holds. The tiers still supply what a diff
  never carries (about three context lines per change, no signatures, bodies, types, or importers):
  Tier 1's surrounding lines and signatures, Tier 2's spec heading, Tier 3's consumers, the prompt
  tier, and the server-response contract supplement.

**Tier 1 — Hunks+** (~15–20% of full context): Diff hunks + 15 surrounding lines + function/class
signatures of changed functions. Assigned to: **Code Quality**

**Tier 2 — Function scope + spec** (~40–50% of full context): Full functions containing changes +
type definitions + import statements. Assigned to: **Product Flow**

**Spec in every code-mode package.** Code modes are self, changes, and PR (`CODE_MODES` in
`crew-review-findings.py`); spec and idea reviews already send the whole artifact. This section owns
the rule. When the task dir has a SPEC.md, append the output of
`crew-review-findings.py spec-context --persona <name> "$TASK_DIR/SPEC.md"` under a `## Spec` heading.
Product Flow gets the whole spec; every other persona gets it without `## Tasks` and `## Hints`,
which are implementation steps only Product Flow checks against the diff.

**Tier 3 — Function-scoped + consumers**: For each changed file: use Grep to locate changed
function/class boundaries, then Read only those line ranges (not the full file). Include import
statements at the top of each file. Also include files that import from changed modules (discovered
via grep for import/require paths), applying the same function-scoped extraction — not full-file
reads. If `EXPLORER_SUMMARY` is non-empty, append it under a `## Codebase context (from explorer)`
heading at the end of the Tier 3 package. Assigned to: **Adversarial**, **Architecture**

**Server-response contract supplement:** When a changed behavior depends on a server response, add
the response type or schema and one direct producer or consumer to the Architecture and Product Flow
packages. This establishes the API contract without expanding every persona package.

**Prompt tier — full prompt + direct contract context**: For each changed prompt, instruction,
skill, or agent file, include the complete changed file rather than only hunks. Include directly
referenced prompts, skills, tools, evaluators, and model/runtime configuration when they can be
identified from imports, links, or nearby paths. Include relevant failing examples or acceptance
criteria when provided. Do not include unrelated repository files. Assigned to: **Prompt Quality**

Under the spine strategy, build each tier by extracting the appropriate scope via Grep + targeted
Read. Below the threshold the diff already serves as the hunk source, so extraction is limited to
the additions named above. For non-prompt tiers, never embed a full file in a context package unless
the file is under 50 lines. Prompt files are the explicit exception above. Under the spine strategy,
limit Tier 3 to spine files + consumers.

## Reading map

When `$REVIEW_ROOT/layers.json` exists, append a `## Reading map` section to **every** persona
package, in the position the section order gives it — after `## Spec` and before guidance. It tells
the persona what order to read the diff in, which is the one thing a size-tier package cannot express:

```markdown
## Reading map

Hunks are nightshift-style ids (`h1`, `h2`, …) from the hunk index. Read layers in this order; earlier
layers explain later ones.

Your primary layers: 1, 3

### 1. foundation — Types and the config contract
Explain: <layer explainer, verbatim>
Focus: <layer reviewFocus, verbatim>
Hunks: h1, h4
  - h4: <hunk note when present>
  - h4: lines omitted (diff too large); read the file if this hunk matters to your lens

### 2. core — …
```

**Primary layers.** Name the layers whose `kind` matches the persona's lens, in reading order. The
persona still reads every layer, but spends its fetch budget on the primary ones first. Omit the line
when no layer matches.

| Persona | Primary kinds |
| --- | --- |
| Adversarial | `core`, `foundation`, `wiring` |
| Architecture | `foundation`, `wiring` |
| Code Quality | `core`, `tests`, `mechanical` |
| Product Flow | `ui`, `wiring`, `docs` |
| Prompt Quality | `prompts` |

**Omitted lines.** For each hunk that `hunks.json` marks `suppressed` (lines dropped for size) or
belongs to a file marked `generated`, add a sub-bullet saying so, as in `h4` above. A persona must
not report a hunk with omitted lines as clean.

The map is orientation, never evidence: a claim still needs a verified `path:line` from the package,
and every `[blocking]` or `[attention]` finding cites the hunk ids that cause it next to the anchor
(`src/a.ts:42 (h7)`) — the full rule is under "Step 5" above. Do not treat layer boundaries as review
boundaries — a finding that spans two layers cites hunks from both.

**Explainer and hunk-note claims are not evidence either.** A persona treats a factual claim in
`Explain:` (config keys, dependencies, unshown background) as unverified until its package grounds it.
Same for `hunkNotes`.

### Spine files (size-gate strategy)

A diff over roughly 30 changed files or 1,500 changed lines uses the spine strategy. The **spine** is
every changed file that either exports a symbol the change adds or edits, or is an entry point
(route handler, CLI command, hook, agent/skill protocol, config that changes runtime behavior). Its
**consumers** are files that import from a spine file or invoke it by name.

Everything else in the diff is context, not spine: keep those files out of persona packages except
for their hunks. The gate emits one line before dispatch so the choice is auditable:

```
Size gate: spine strategy — N spine files, M consumers, K files as hunks only
```

A diff below that threshold uses the complete diff and emits:

```
Size gate: full diff — N files, M changed lines
```

### PR review mode

The tiers above, built from the PR-head files in `$REVIEW_ROOT/head/files/`: [PR review
mode](pr-mode.md), "Context packages".

### Spec review mode

No context tiers — all reviewers receive the full SPEC.md text.

### Idea review mode

No context tiers — all reviewers receive the full artifact text (pasted text or session conversation
summary).

## Package section order

`crew-assemble-packages.py` emits one order: shared head (contract, lookups, mode, `## Hunk reference`,
`# Repo memory`), then `# Diff` with `package.diff` in full, then the per-persona tail (`# Size gate`,
`## Spec`, `## Reading map`, `# Repository guidance`, prior-round block, consumers, `# Prompt tier`,
`## Questions for this lens`). Absent sections are omitted; the rest keep this order. Head and diff are
identical in a run's packages, so a prefix cache pays once (`test_assemble_packages.py` pins it).

## Repo memory and guidance

`prepare` (Step 2 of [crew-reviewer](../../crew-reviewer.md)) writes `mem.md` (review-mode recall over
the changed files) and `agent-context.json` (guidance from repository root to nearest folder, each
file once). Every package carries the memory under `# Repo memory`, in the shared head; with no store
it is `warning: memory unavailable`, and the summary names the gap. A missing or empty
`agent-context.json` stops `crew-assemble-packages.py` with exit 2: rerun `prepare` from the reviewed
repo's checkout, or pass `--root`.
