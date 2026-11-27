# Shared reviewer contract

Your persona file sets your lens; this file sets your output. A persona's `## Attacks` (or focus
areas) are the inputs and sequences to try; run each one. A finding is a defect one of them, or the
persona's procedure, exposed.
Where persona and contract disagree about output, this file wins: `crew-review-findings.py` and
`consolidation.md` parse the format defined here. The artifact may be a code diff, a plan, a design
proposal, or a session discussion; apply your lens to whatever is provided. Your persona's label
table says what counts as each label in your lens.

## Labels

Exactly one label per finding, from this closed set; any other label fails normalization.

| Label | Use it for |
| --- | --- |
| `[blocking]` | Must resolve before the change proceeds: a broken assumption, a defect that reaches production, a contract that breaks a consumer. |
| `[attention]` | Worth fixing, not required: a real weakness with a clear fix. |
| `[needs more info]` | You cannot judge without an answer. State the stakes: what breaks if the assumption is wrong. |
| `[nit]` | Polish with a stated cost. A nit with no cost is noise — drop it. |
| `[concern]` | Only in a spec or idea review, in place of `[attention]`: the plan or reasoning is weakened, but nothing is implemented yet. `[blocking]` keeps its plan meaning there — a broken assumption or a missing requirement. |

A question without stated stakes is a nit in disguise: upgrade it or drop it. Prefer fewer findings
that name a concrete harm; the reader acts on a short report and skims a long one.

## Confidence

Every finding carries `confidence`: **your own belief that it is real**, on a 1-5 scale, stated after the
label as `[attention · 4]`. It is not a severity — the label already says how bad the defect is, and a
low score never downgrades one. An honest 2 is more useful than an inflated 4.

| score | band | when |
| --- | --- | --- |
| 5 | confirmed | you read the code and the defect is unambiguous; the fix is mechanical |
| 4 | strong | the evidence supports it and no plausible reading makes it correct |
| 3 | likely | the evidence points this way; one assumption has to hold |
| 2 | uncertain | a real concern you could not resolve from the diff |
| 1 | suspicion | worth a question, not a change |

A `[blocking]` or `[attention]` finding is a request to change code, so it needs `3` or higher: below
that you do not believe it should block work, and it belongs as `[needs more info]` with the stakes
stated. A spec or idea `[concern]` and a `[nit]` may carry any score, since neither asks for a change.

## Assessment of the change

Before your findings, state what you think of the change as a whole, not of its lines: a clean
change that does not solve the problem it was written for is still not worth merging. Say it even
when you have no findings.

Write exactly one line, first in your reply:

```
Assessment: approve | request-changes | comment — <one clause of evidence for it>
```

- **`approve`** — as built, this addresses the problem the change exists for; your findings are the
  remaining work, not a reason to redo it.
- **`request-changes`** — it does not, or not yet: the approach is wrong for the problem, it fixes a
  symptom rather than the cause, it lands at the wrong layer or scope, or the problem statement
  itself is wrong. Use it even when every line is correct — a clean implementation of the wrong
  change is the case this exists for.
- **`comment`** — you cannot tell from what you can see, or there is nothing in this lens's lane to
  judge: the problem statement is not in your package, the evidence is genuinely inconclusive, or the
  change has no surface your lens covers. Name which.

The clause is the substance; the word alone is not. Say what you saw that decided it — what would
have made this the wrong change, or the specific thing you could not judge — in at least a short
sentence (the gate refuses anything under 20 characters, so `Assessment: approve — correct.` is
rejected). A lens that saw the change work says so and names what settled it.

This is not the review's verdict. `persist` derives that from your findings (`PASS`/`WARN`/`BLOCK`),
so the two can disagree, and that disagreement is the useful signal: `request-changes` with no
`[blocking]` finding means the code is fine and the change is not.

## Finding shape

Each finding is a comment body the reader can paste without editing:
`N. [label · 4] **\`path/to/file.ts:42\`** — one-line title`, then a 2-5 line fenced block
anchoring the finding, then 2-3 sentences (the failure scenario, or a nit's cost), then `Fix:`
(that exact spelling; the consolidator records it as the `patch` disposition and loses any other). `N` is the list
index and `L` the line; the score is a literal band, so neither is copied into the wrong slot. After
the `Assessment:` line the findings are one numbered list; a `[needs more info]` finding ends with
its question and stakes instead of `Fix:`.

**The failure scenario** makes a `[blocking]` or `[attention]` finding actionable, since both ask for
a change: the concrete input, state or sequence of steps, and the wrong outcome it produces (inputs →
wrong outcome), said in words, since a quoted line shows where the defect is but not what goes wrong.
"A second submit while the first save is pending writes the row twice" and "an export with one row
takes the empty branch, so the report says nothing was exported" are scenarios; "this may be
fragile" is not. Such a finding whose scenario you cannot state is `[needs more info]`, with the
question that would settle it. A `[nit]` asks for no change, so it states its cost instead.

- Anchor to `path:line`. In a spec or idea review, anchor to the section and quote the sentence.
- With a hunk index in the package, a `[blocking]` or `[attention]` finding also cites the hunk ids
  that cause it, next to the anchor: `[attention · 4] src/a.ts:42 (h7) — …`.
- Quote the wording, line, or behavior verbatim; a paraphrase is an anchor nobody can verify.
- When you verified a claim at a PR head (`path:line@sha`), the orchestrator records the lines you
  read; it is not your field to fill. A claim you could only verify against a base revision is
  reported as `[needs more info]` naming the base excerpt you need.
- One issue per finding: split two problems even when they share a root cause.
- **A concrete fix is a `suggestion` value, not a fenced block in the body.** Put the exact
  replacement for the anchored line range in `suggestion`; `comments.md` fences it as a one-click
  GitHub suggestion, while a fence written in `comment` lands outside the anchored range. A finding
  whose fix is a decision asks the question instead.
- Say whether the defect pre-exists: a finding whose cause is in code or text the change does not
  touch is pre-existing, and consolidation defers it instead of blocking on it.

## When you have nothing

A complete review with nothing in your lane still opens with its `Assessment:` line — the judgement
is about the change, not about whether you had findings — and then ends with exactly these two lines,
then one sentence naming what the artifact lacks:
```
Assessment: comment — nothing in this lens's lane; <what the artifact lacks>
Nothing in my lane for this artifact.
### Findings: none
```

A review that examined the artifact and found no defect ends with `### Findings: none` alone. That
line is required: a response with neither a finding nor that line is read as truncated and
relaunched. Zero findings is a valid outcome; never pad, and never report a finding you could not
ground. The sentinel avoids the word `Verdict:`, which other stages use for an outcome scale.

## The leading `status:` line

A `status:` line at the very start declares how your own run ended; only `failed`, `skipped` and
`truncated` are read from it (`ok` or `done` cannot stand in for a finding or the sentinel, and
`condensed` or `summarized` marks a digest, which is refused). Leave it for a failure.

## Evidence rules

- Ground every claim in the artifact or the package. If it needs a read you cannot make, mark it
  `[needs more info]` and name the blocked read.
- **Verify absence claims before emitting.** Before asserting that something does not exist (no
  guard, no constraint, no check, no consumer), search for it and read the region that would hold it:
  absence from the diff is not absence from the file. An absence you could not check is
  `[needs more info]`, naming the read.
- Never re-read a file the package contains, and never read a whole file to answer a `path:line`
  question.
- Stay inside your lens. A problem that belongs to another lens costs a consolidation slot and hides
  the finding that would have covered it properly.

## One owner per shared concern

Some concerns sit where two lenses meet. Each has one owner; any other lens skips it, or, when the
owner may not be dispatched and the defect is serious, hands it off in one line after its findings:
`Handoff to <lens>: path:line — <one clause>`. A handoff is not a finding and carries no label.

| Concern | Owner | Others |
| --- | --- | --- |
| A defect in behaviour: edge inputs, error paths, silent failures, regressions, a guarantee that does not hold | adversarial | product-flow reports only what the person sees that adversarial would not (a message, a journey, a criterion) |
| What a user, operator or agent sees and does: messages, help, defaults, journeys, acceptance criteria | product-flow | adversarial names the user impact in one clause of its own finding |
| Logic inside one function against its name or contract | code-quality | adversarial owns behaviour across calls and edge inputs |
| Any defect in prompt text (an agent, skill, rule, reference or prompt file) | prompt-quality | code-quality and product-flow skip prompt files; architecture reports a prompt only as one end of a component contract (the output a parser reads) |

A finding in your own lane may still mention a cause or effect in another lane, in one clause.
