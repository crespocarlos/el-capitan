# Evidence, comments, and records

Step-level detail `crew-reviewer` needs only in PR mode or at persistence time. Each section names the
gap it closes, so the rule that produced it stays visible instead of becoming an unexplained
requirement.

## A PR-head finding stores its excerpt

A finding verified at the PR head carries `path:line@headSHA7`, and that label alone cannot be read
back: the head is not in the local checkout, and the review directory outlives both the session and
the network access that produced it. Re-checking four recorded findings cost five `gh api` reads and
three file reads, so the record could not prove itself offline.

Every `[blocking]` and `[attention]` finding whose `evidence` uses the `@sha` form carries `excerpt`:
the two or three lines actually read. `normalize` and `persist` refuse the finding without it. A
working-tree finding needs none, because the checkout still holds its lines; the gate is scoped to the
form that cannot be re-read.

## One base read per regression claim

"This used to behave differently" is a claim about a tree nobody read, and asserting it from the head
alone is a guess. A regression claim allows exactly one additional `gh api` read at `baseRefOid`, with
the evidence labeled `path:line@<base7>`, and `validation` names the two reads the comparison rests on.
The allowance is per claim, not per review, and it opens no local checkout: a base read is a network
read at a different SHA. Without it the honest outcome is `[needs more info]` naming the base excerpt
that could not be read.

## Paste-ready comments

A PR review's findings are read by someone else, so the report is not the only output. Each emitted
`blocking`, `attention`, and `needs more info` finding carries a `comment` field: the body as it will
appear on the PR, in `~/.cursor/rules/voice.mdc`'s review-comment voice. First person, usually one or
two sentences, phrased as a question or suggestion rather than an order, `nit:` for something small,
and a ```` ```suggestion ```` block when the fix is a concrete edit. Anchor the comment to the same
`path:line` the finding carries.

**Write the body yourself, as the step that writes `candidates.json`.** No persona supplies `comment`
— `reviewer-contract.md` defines one body per finding, and the reviewer is forbidden to invent
findings — so this is the orchestrator's text, composed from the finding it already holds. Omitting it
costs the comment, never the review.

`persist --mode pr` writes one section per anchor to `comments.md` and reports the path. A finding with
no `comment` is named on stderr and costs only the file, never the report: the review is valid without
it, and losing a whole review over wording would cost more than the warning. To re-render after adding
bodies:

```bash
~/.agent/bin/crew-review-findings.py comments --review-dir "$REVIEW_ROOT" --head <headSHA>
```

It exits 1 naming each finding still missing a body, so a partial file never reads as the whole set.
Nothing in this path calls `gh`. Posting is external state the user asks for separately; the draft is
what they paste.

## Dropped findings are recorded

`MAX_NITS` against a dozen candidates forces real drops, and a dropped finding with no artifact is
invisible to the reviewer who raised it. Every finding consolidated as `dropped` carries a `reason` and
lands in `DROPPED.md` beside the task's deferred list, so "not now" and "no" stay distinguishable.

Order nits by evidence strength before cutting: a nit whose cost is shown in the diff outranks one
whose cost is argued, and one two personas independently raised outranks a single lens's polish. Never
drop a severity finding to keep a nit; the two budgets count separately.
