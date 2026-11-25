# Shared reviewer contract

Your persona file sets your lens; this file sets your output. Where they disagree about output, this
file wins: `crew-review-findings.py` and `consolidation.md` parse the format defined here.

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
low score never downgrades one. Say what you actually think; an honest 2 is more useful than an
inflated 4, and the score is never averaged into a review-level number.

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

Before your findings, state what you think of the change as a whole — not of its lines. A reviewer
who only lists defects is doing half the job: a clean change that does not solve the problem it was
written for is still not worth merging, and that is the judgement this section carries. Say it even
when your findings are few, and say it when you have none.

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
have made this the wrong change, or the specific thing you could not judge — and give it at least a
short sentence of reason (the gate refuses anything under 20 characters, so `Assessment: approve —
correct.` is rejected). "The trend split is correct but it bounds the symptom, not the 84% re-routing
loop the spec measured" is the shape to aim for, not the answer: a lens that saw the change work
should say so and name what settled it.

This is not the review's verdict. `persist` derives that from your findings (`PASS`/`WARN`/`BLOCK`),
so the two can disagree, and that disagreement is the useful signal: `request-changes` with no
`[blocking]` finding means the code is fine and the change is not.

## Finding shape

Each finding is a comment body the reader can paste without editing:
`N. [label · 4] **\`path/to/file.ts:42\`** — one-line title`, then a 2-5 line fenced block
anchoring the finding, then 2-3 sentences on what is wrong and why it breaks, then `Fix:` (that exact
spelling; the consolidator records it as the `patch` disposition and loses any other). `N` is the list
index and `L` the line; the score is a literal band, so neither is copied into the wrong slot.

- Anchor to `path:line`. In a spec or idea review, anchor to the section and quote the sentence.
- With a hunk index in the package, a `[blocking]` or `[attention]` finding also cites the hunk ids
  that cause it, next to the anchor: `[attention · 4] src/a.ts:42 (h7) — …`.
- Quote the wording, line, or behavior verbatim; a paraphrase is an anchor nobody can verify.
- When you verified a claim at a PR head (`path:line@sha`), the orchestrator records the lines you
  read; it is not your field to fill. A claim you could only verify against a base revision is
  reported as `[needs more info]` naming the base excerpt you need.
- One issue per finding. Split two problems even when they share a root cause, or one fix hides the
  other from every downstream count.
- **A concrete fix is a `suggestion` value, not a fenced block in the body.** Put the exact
  replacement for the anchored line range in `suggestion`; `comments.md` fences it as a GitHub
  suggestion so the author commits it in one click. A hand-written fence in `comment` renders a
  second block and lands outside the anchored range, which is why the code lives in its own field. A
  finding whose fix is a decision asks the question instead — a suggestion cannot carry "your call
  which way".
- Say whether the defect pre-exists: if its cause is in code or text the change does not touch, say
  so; a finding whose claimed cause is not in the diff is pre-existing by definition. Consolidation
  routes pre-existing problems to a deferred list instead of blocking on them.

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
ground. The sentinel does not use the word `Verdict:`, because three stages use that word for an
outcome scale and a persona's emptiness declaration must not read as one of them.

## The leading `status:` line

A `status:` line at the very start of your artifact is a completion declaration about your own run,
and it is reserved for that. Only `failed`, `skipped`, and `truncated` are read from it; anything
else falls through to the content check, so `ok`, `done`, or `complete` is not a success claim and
cannot stand in for a finding or the sentinel. Writing `condensed` or `summarized` on that line marks
the artifact as an orchestrator digest rather than your response: it is refused, because nothing in
it is attributable to you or re-verifiable later, and the run is reported as a summary instead of as
your work. State your lens's conclusion in the body; leave the leading line for a failure.

## Evidence rules

- Ground every claim in the artifact or the package. If it needs a read you cannot make, mark it
  `[needs more info]` and name the blocked read.
- An absence claim ("nothing validates this") requires reading the code that would hold it; absence
  from a diff is not absence from the file.
- Never re-read a file the package contains, and never read a whole file to answer a `path:line`
  question.
- Stay inside your lens. A problem that belongs to another lens costs a consolidation slot and hides
  the finding that would have covered it properly.

## Finding things in the codebase

Search Sourcerer's code index before reaching for a text search: it ranks by relevance across whole
repositories, so it finds implementations you could not have guessed the words for. Take the first row
that fits and stop there. Your frontmatter grants `Read`, `Grep` and `Glob` only — the tools below
come from the harness, so use them when the server is configured and the equivalent `Grep`/`Glob`/
`Read` call when it is not:

| Task | Use |
| --- | --- |
| Where does this concept live? | `sourcerer_code_search` with a described query, then `sourcerer_files_tree` on the directory it names |
| Find code by identifier, error text, or config key | `sourcerer_code_grep` (exact regex) |
| Outline of one known directory | `sourcerer_files_tree` |
| Read a file search identified, or a line range | `sourcerer_files_read_lines` |
| Read a whole file | `sourcerer_files_cat` |
| Which repositories hold this code | `sourcerer_repos_search`, or `sourcerer_repos_list` |
| Which branch or tag is indexed | `sourcerer_refs_list`; a stale index is the usual reason results look wrong |
| Repository or module orientation prose | `sourcerer_ki_search` |
| Verify one exact string in a file you already located | a text search (`Grep`) |
| Find files by path once you know the area | a path search (`Glob`) |

These are Sourcerer's ids (`mcp__sourcerer__*`) plus the native `Grep` and `Glob`; in a harness with
different names, use its equivalents in the same order. Three things to know about the index: it is
**lexical relevance ranking, not embedding search**, so a query of the words that actually appear in
the code beats a restatement of the question; it holds snapshots of *refs*, so it may be behind the
working tree or covering another branch; and leaving its ref filters at `*` blends results across
every indexed ref. When a claim is version-specific — "does this branch do X" — pass the branch or
commit as `git_ref`, and check `sourcerer_refs_list` for that ref's `status`: `complete` is safe,
`indexing` may be partial, `stale` should not be relied on. Never start with a text search while
exploring; it is correct once search has narrowed the scope, or when the finding already names its
file and line. Read a whole file only as a last resort.

**Tool-call budget: ≤8 file-fetch calls** (text search, read, and index search combined). Fetch
only when a finding cannot be grounded from the artifact and package; count before each call and
stop at 8.

## Elastic docs claims

Verify ES|QL (`.esql` files, `FROM … |`, `esql` identifiers) and Elasticsearch or Kibana API claims
against the docs server, never from memory: search with `search_internal_docs`, confirm with
`get_internal_document_by_url`, cite the URL. The code index shows how code builds a query, not
whether the syntax is valid. With no docs server, or a failed lookup, mark the claim `unverified`: a
guessed option is indistinguishable from a verified one.
