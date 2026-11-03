## Step 7: Consolidation

Collect all reviewer outputs. Consolidation starts from persona text but decides against the
repository: every `[blocking]` and `[attention]` candidate is verified in the source before it is
kept (see "Verify against the repository"). Never re-review the artifact for new findings.

**Completion check:** Before evaluating a persona response, treat it as incomplete only when the
harness reports truncation, it ends mid-sentence/list/code fence, or it contains neither a
`### Verdict: no findings` line nor a complete labeled finding. A short response alone is valid. Relaunch an
incomplete persona once with a narrower evidence package and a request for a complete verdict; if it
remains incomplete, persist the failure artifact and name the gap under `### Reviewers`.

### Challenge each finding before keeping it

Before deduplication, interrogate every finding. The primary question is not "is this correct?" but
**"is this assessment grounded — does the reasoning actually follow from the artifact?"** Reviewers
are LLMs and will sometimes produce confident-sounding findings that contradict each other,
contradict the artifact, or are simply pattern-matched noise.

**Step 7a — Scan session history for prior reviews**

Before evaluating any finding, scan the visible session conversation for previous `crew review`
outputs (look for `## Review:` headings). If found, build a lightweight map of prior findings and
decisions: what was flagged, what was approved, what was explicitly dismissed. This is your
cross-session consistency baseline.

**For idea review:** also check the artifact itself for a `## Decisions` section. If present, treat
every entry there as already-decided: do not re-raise a `[rejected]` finding unless you have
specific new evidence the rejection was wrong (state that evidence explicitly). A `[deferred]`
finding may be raised again only if it is now clearly in-scope for the current revision.

For each finding in the current review, ask:

**Does it contradict a prior review in this session?** If a reviewer now recommends X but a previous
review in this session recommended not-X (or vice versa), that is a drift signal — not automatically
wrong, but it requires an explanation. Surface it: `(session drift: previous review at [approx
time/position] recommended [opposite] — reviewers should not flip without a stated reason)`. If no
reason is apparent from the artifact change, downgrade the finding to a question and ask which
position holds.

**Is the reasoning traceable?** Can you trace a direct line from the artifact to the conclusion? If
a reviewer says "X will cause Y", is X actually present and does it actually cause Y? If the chain
breaks anywhere, mark it: `(ungrounded: [where the chain breaks])` and either repair it or drop it.

**Is it internally consistent within this review?** Does this finding contradict another finding
from the same reviewer in this same run? Contradiction is a signal that the reviewer was
pattern-matching rather than reasoning. Surface it: `(note: conflicts with [other finding] — kept
the stronger one)`.

**Is the severity proportionate to actual impact?** Ignore the persona's label and assign one from
the verified harm. A `[blocking]` must name a concrete failure path. If the harm is speculative or
relies on an unlikely chain of events, downgrade: `(downgraded: harm is speculative — no direct
failure path in this artifact)`.

**Is it specific enough to act on?** Vague findings ("this could be improved", "consider handling
this case") with no concrete target are noise. Either sharpen with what you know of the artifact, or
drop: `(dropped: too vague to act on)`.

**Do the stakes hold up?** Every question must name what breaks if the answer is wrong. If it
doesn't, add the stakes or convert to a nit.

The goal is a report where every finding has a traceable, defensible reason to exist — not a relay
of whatever the reviewers returned.

### Verify against the repository

In PR mode, "the repository" is the PR head read through `gh` (`gh pr diff`, `gh api
.../contents/<path>?ref=<headSHA>`), never the local working tree and never a checkout of the PR.
The two targeted reads below mean up to two `gh api` reads at that head SHA. Do not validate a PR
finding through local `Read`, `Grep`, semantic search, or filesystem commands.

For each `[blocking]` and `[attention]` candidate in a code review, confirm the claim in the current
source with at most two targeted reads (the cited lines plus one caller, guard, or definition).
Judge each finding on its own evidence, never by analogy to another finding. Absence claims ("there
is no guard") always need this check, because personas see truncated slices. Claims about filesystem
or persisted-data state ("symlink is a real directory", "existing specs use the old format") also
need one command (`ls -la`, a count over the real data), because Ask-mode personas cannot run shell
commands. This local-state check does not apply in PR mode unless the claim concerns the local
reviewer environment. When a `[blocking]` claim needs more than two reads, dispatch one read-only
validator subagent (`reviewer-explorer`) with only that claim and its location, and keep its
verdict. In PR mode, its prompt must include the PR repository, head SHA, exact claim, and PR-head
excerpts; it must return `[needs more info]` rather than use local tools. Outcomes:

- **confirmed** — keep, with the evidence location in the internal record.
- **refuted** — drop: `(dropped: refuted by <path:line>)`.
- **unverifiable** (blocked reads, missing context) — downgrade to `[needs more info]` naming the
  blocked check, or drop.

Spec and idea reviews verify claims against the artifact text instead; verify repository claims
inside them the same way.

### Not a finding

Drop these regardless of label:

- problems that already existed before this change and that the change does not touch or worsen —
  route to `defer`;
- anything a configured linter, formatter, or type-checker reports;
- pedantic style preferences with no stated cost;
- issues the code explicitly silences or documents as intentional (an ignore comment with a reason,
  a linked issue);
- duplicates of a finding the user rejected earlier in the session, unless new evidence is stated.

### Route

Give each kept finding a disposition in the internal record:

- **patch** — has a concrete `Fix:` inside the reviewed scope.
- **decide** — needs a user choice (scope, contract, trade-off); emit as `[needs more info]` with
  the options.
- **defer** — real but pre-existing or outside the reviewed scope. Do not emit it in the numbered
  list; append it to the deferred file (see pipeline persistence) and mention the count in one line
  after the list.

### Selective empirical verification

After the repository check, classify each remaining `[blocking]` or `[attention]` candidate as
**static**, **runtime-verifiable**, **prompt-evaluable**, or **human-judgment**. Verify only
runtime-verifiable and prompt-evaluable candidates that have a concrete failure path:

- Use an existing targeted test, eval, API request, or configured live-cluster query when one is
  available.
- Reuse the same fixture or query for related findings instead of running one check per finding.
- Cap empirical checks at two focused checks per review; do not start a cluster or run a broad suite
  solely for review.
- Downgrade or drop findings that remain speculative after the check.
- Nits and naming findings do not require empirical verification.

Record the verification result and command or evidence source in the internal finding record so the
final finding can distinguish static evidence from observed behavior.

### Deduplication

Deduplicate aggressively — same concept flagged at different locations still counts as one finding
if the root cause is the same. When two or more reviewers flag the same issue:

1. Keep the finding with the strongest label (`[blocking]` > `[attention]` > `[needs more info]` >
   `[nit]`)
2. Note which reviewers flagged it: `(also flagged by: Adversarial, Code Quality)`
3. Merge any complementary details into the kept finding

Label ordering for deduplication: `[blocking]` > `[attention]` > `[needs more info]` > `[nit]`.

### Grouping

Both modes use a flat numbered list. Severity is an inline label on each finding — no sub-sections.

Severity labels and what they mean:

| Label               | Meaning                                                           |
| ------------------- | ----------------------------------------------------------------- |
| `[blocking]`        | Must fix before merge / must resolve before proceeding            |
| `[attention]`       | Meaningful improvement — worth doing, not required                |
| `[needs more info]` | Something unclear that needs an answer before it can be evaluated |
| `[nit]`             | Minor — polish, naming, style                                     |

For idea/spec reviews, use `[concern]` instead of `[attention]` and `[blocking]` to signal whether
the plan or reasoning holds up.

<critical_rules>

1. Every code review finding MUST include a `file:line` reference. Findings without a file anchor
   are unactionable — drop them or trace the file before emitting.
2. Code snippets (2-5 lines) are REQUIRED on `[blocking]` findings. Recommended on `[attention]`.
   Omit on `[nit]` unless the fix is non-obvious.
3. Hard cap: 7 findings total. After deduplication, keep highest-severity. Drop the rest entirely.
4. Zero findings is valid. No action plan. No reviewers section. No padding.
5. Per-finding length: code snippet (2-5 lines) anchoring the finding, explanation (2-3 sentences),
   fix (1-2 sentences or code block). Every sentence must add information — do not pad.
6. For idea/spec review: `Fix:` field required on every `[blocking]` and `[concern]` finding —
   actionable enough for mechanical application.

</critical_rules>

<output_format mode="code_review">

Each finding is a self-contained GitHub PR comment body — written to be pasted inline without
editing. Use one flat numbered list with an inline severity label; do not add severity headings.

````
## Review: <mode> — <summary>

1. [blocking] **`path/to/file.ts` — line N**

```lang
<2-5 lines anchoring the finding>
````

<What the code does wrong and why it breaks. 2-3 sentences.>

Fix:

```lang
<concrete fix when the fix is unambiguous — omit otherwise>
```

---

2. [attention] **`path/to/file.ts` — line N**

```lang
<2-5 lines, recommended>
```

<What to address and why. 2-3 sentences.>

Fix: <text description, or code block when concrete>

---

3. [needs more info] **`path/to/file.ts` — line N**

```lang
<relevant lines>
```

<Question with stated stakes — what you need to know and what breaks if the assumption is wrong.>

---

4. [nit] **`path/to/file.ts` — line N** — <what to change, one line>

```

</output_format>

<output_format mode="idea_spec_review">

Tone is evaluative — "does this hold up?". Findings address whether the idea, plan, or reasoning is
sound.

```

## Review: Idea — <summary>

**Verdict:** proceed / revisit / blocked — <1 sentence: the decisive reason>

1. [blocking] **<title>** — <what assumption breaks or what is fundamentally missing>. <why it matters>.
   **Fix:** <exact change — what sentence/section to add, remove, or reframe. Specific enough for mechanical application.>
2. [concern] **<title>** — <what weakens the plan>. <why it matters>.
   **Fix:** <what would strengthen it — specific framing or addition.>
3. [needs more info] **<title>** — <what is unclear and must be resolved before moving forward>.
4. [nit] **<title>** — <minor framing or completeness improvement>.

````

If there are no findings, state the verdict as `proceed` and give one sentence of reasoning.

</output_format>

<output_discipline>

- No extra structure. No sub-sections, no thematic groupings, no preamble. Flat numbered list only.
- Be opinionated. Surface what matters most, not everything found. A short focused report beats an
  exhaustive one.
- Never emit a finding you cannot anchor to a specific file location (code review) or a specific
  claim in the artifact (idea review).

</output_discipline>
