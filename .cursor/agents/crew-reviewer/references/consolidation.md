## Step 7: Consolidation

Collect all reviewer outputs. Consolidation starts from persona text but decides against the
repository: every `[blocking]` and `[attention]` candidate is verified in the source before it is
kept (see "Verify against the repository"). Never re-review the artifact for new findings.

**Completion check:** before evaluating a persona response, treat it as incomplete only when the
harness reports truncation, it ends mid-sentence/list/code fence, it points at an earlier turn instead
of carrying the list, or it contains neither a complete `### Verdict: no findings` line, a complete
documented finding, nor an explorer section with an item. A short response alone is valid.

Recovering an incomplete response is a dispatch rule, not a consolidation one: a pointer reply is
resumed once, anything else relaunched once with a narrower package, per **A reply that points at an
earlier turn** in the shared dispatch instructions. This file owns only the outcome: if recovery also
fails, persist a failure artifact for that persona and name the gap under `### Reviewers`.

A response carrying both anchored findings and a trailing `### Verdict: no findings` is complete:
content wins, and a verdict line never cancels findings above it. Note the contradiction under
`### Reviewers` rather than silently dropping either half.

### Challenge each finding before keeping it

Interrogate every finding before deduplication. The primary question is not "is this correct?" but
**"is this assessment grounded — does the reasoning follow from the artifact?"** Reviewers are LLMs
and will sometimes produce confident findings that contradict each other, contradict the artifact, or
are pattern-matched noise.

**Step 7a — scan session history for prior reviews.** Scan the visible conversation for previous
`## Review:` headings, and build a map of prior findings and decisions: what was flagged, approved,
and explicitly dismissed. For an idea review, also check the artifact for a `## Decisions` section and
treat every entry as decided: do not re-raise a `[rejected]` finding without specific new evidence
(state it), and re-raise a `[deferred]` one only when it is now clearly in scope.

For each finding, ask:

**Does it contradict a prior review in this session?** If a reviewer now recommends X and an earlier
review recommended not-X, that is drift: it needs a stated reason. Surface it as `(session drift:
previous review recommended [opposite] — reviewers should not flip without a stated reason)`, and when
no reason appears in the artifact change, downgrade it to a question.

**Is the reasoning traceable?** Can you trace a direct line from the artifact to the conclusion? If a
reviewer says "X will cause Y", is X present and does it cause Y? Where the chain breaks, mark
`(ungrounded: [where the chain breaks])` and repair or drop it.

**Is it specific enough to act on, with proportionate stakes?** A finding must name a concrete target
and say what breaks; otherwise sharpen it or drop it. Ignore the persona's label and assign one from
the verified harm: `[blocking]` names a concrete failure path, and speculative harm or an unlikely
chain downgrades. Mark a downgrade `(downgraded: harm is speculative — no direct failure path in this
artifact)` and a drop `(dropped: too vague to act on)`.

**Does it contradict another finding in this run?** Two findings can each be grounded and still be
mutually exclusive ("the guard is unreachable" versus "the guard fires before validation"), which
per-finding traceability cannot see. Surface it as `(note: conflicts with [other finding] — kept the
stronger one)`. Deduplication handles one issue flagged twice; this handles two that cannot both hold.

The goal is a report where every finding has a traceable, defensible reason to exist — not a relay.

### Verify against the repository

In PR mode, "the repository" is the PR head read through `gh` (`gh pr diff`, `gh api
"repos/.../contents/<path>?ref=<headSHA>"` with the URL quoted), never the local working tree and never
a checkout of the PR. The two targeted reads below mean up to two `gh api` reads at that head SHA. Do
not validate a PR finding through the local checkout — no file reads, repository search, or other
filesystem commands, whatever the harness calls them. When the cited path itself is uncertain, list
the parent directory in one call rather than fetching guessed paths.

For each `[blocking]` and `[attention]` candidate in a code review, confirm the claim in the current
source with at most two targeted reads (the cited lines plus one caller, guard, or definition). Judge
each finding on its own evidence, never by analogy. Absence claims ("there is no guard") always need
this check, because personas see truncated slices. Claims about filesystem or persisted-data state
("symlink is a real directory", "existing specs use the old format") also need one command (`ls -la`,
a count over the real data), because Ask-mode personas cannot run shell commands; that check does not
apply in PR mode unless the claim concerns the local reviewer environment. When a `[blocking]` claim
needs more than two reads, dispatch one read-only `reviewer-explorer` with only that claim and its
location, and keep its verdict. In PR mode its prompt must include the PR repository, head SHA, exact
claim, and PR-head excerpts, and it must return `[needs more info]` rather than use local tools.
Outcomes:

- **confirmed** — keep, with the evidence location in the internal record.
- **refuted** — drop: `(dropped: refuted by <path:line>)`.
- **unverifiable** (blocked reads, missing context) — downgrade to `[needs more info]` naming the
  blocked check, or drop.

Spec and idea reviews verify claims against the artifact text instead, and verify repository claims
inside them the same way.

### Not a finding

Drop these regardless of label:

- problems that existed before this change and that the change does not touch or worsen — route to
  `defer`;
- anything a configured linter, formatter, or type-checker reports;
- pedantic style preferences with no stated cost;
- issues the code explicitly silences or documents as intentional (an ignore comment with a reason, a
  linked issue);
- duplicates of a finding the user rejected earlier in the session, unless new evidence is stated.

### Route

Give each kept finding a disposition: **patch** (concrete `Fix:` inside the reviewed scope), **decide**
(needs a user choice; emit as `[needs more info]` with the options), or **defer** (real but
pre-existing or outside scope — not in the numbered list; append it to the deferred file per pipeline
persistence and mention the count in one line after the list).

Two things are recorded beyond the label and anchor, each under its own condition:

- **`kind`** (required) — what sort of defect, independent of severity. Every finding that reaches a
  gate states one; a finding with none is rejected with the allowed values listed. Values are the
  `KINDS` set in `crew-review-findings.py`; read it there rather than copying it, and never invent a
  value, because the parser rejects one outside it. The boundaries that matter: `correctness` produces
  a wrong result on valid input; `reliability` fails
  under load, timing, or an environmental condition; `testing` is missing or weak coverage of behavior
  the change introduces; `documentation` misstates what the code does; `other` is none of these.
- **`validation`** (when `verified` is true) — one sentence on what you read and concluded, e.g.
  "confirmed: `executeEsqlQuery` returns no rows when `_source` is absent, and this query keeps only
  `data_json`". `verified: true` alone asserts a second read happened; this records why it passed.
  `persist` requires it whenever `verified` is true, in every mode, including one passing no
  `--files`.

When a hunk index exists, carry each finding's hunk ids into its record and check them against the
verified location: correct an id that names a hunk the finding does not depend on, and route a
`[blocking]` or `[attention]` finding that no hunk causes to `defer`, since it is pre-existing.

### Selective empirical verification

After the repository check, classify each remaining `[blocking]` or `[attention]` candidate as
**static**, **runtime-verifiable**, **prompt-evaluable**, or **human-judgment**. Verify only the middle
two, and only with a concrete failure path:

- Use an existing targeted test, eval, API request, or configured live-cluster query when available.
- Reuse one fixture or query for related findings instead of one check per finding.
- Cap empirical checks at two focused checks; never start a cluster or run a broad suite for a review.
- Downgrade or drop findings that remain speculative after the check.
- Nits and naming findings need no empirical verification.

Record the result and the command or evidence source so the final finding distinguishes static
evidence from observed behavior.

### Deduplication and grouping

Deduplicate aggressively — the same concept at different locations is one finding when the root cause
is the same. When several reviewers flag one issue, keep the strongest label, note the others as
`(also flagged by: Adversarial, Code Quality)`, and merge complementary detail.

Label order, also used for deduplication: `[blocking]` > `[attention]` > `[needs more info]` > `[nit]`.

Both modes use one flat numbered list; severity is an inline label, never a section.

| Label | Meaning |
| --- | --- |
| `[blocking]` | Must fix before merge / must resolve before proceeding |
| `[attention]` | Meaningful improvement — worth doing, not required |
| `[needs more info]` | Unclear; needs an answer before it can be evaluated |
| `[nit]` | Minor — polish, naming, style |

In idea and spec reviews, `[blocking]` marks a broken plan fundamental (an assumption that does not
hold, a missing requirement) and `[concern]` replaces `[attention]` for weaknesses worth addressing.
`[blocking]` still blocks, so the verdict mapping in pipeline persistence applies unchanged.

Write each kept finding in the shape [finding formats](finding-formats.md) defines.
