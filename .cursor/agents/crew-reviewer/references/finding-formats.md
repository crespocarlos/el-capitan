# Finding formats

The shape every finding is written in, for both artifact kinds. Consolidation decides *which* findings
survive; this file decides how a surviving one reads.

## Rules

1. Every code-review finding carries a `file:line` reference. A finding with no file anchor is
   unactionable — trace the file before emitting, or drop it.
2. A 2–5 line code snippet is required on `[blocking]`, recommended on `[attention]`, and omitted on
   `[nit]` unless the fix is non-obvious.
3. Hard cap: `MAX_FINDINGS` non-nit findings plus at most `MAX_NITS` nits, both defined in
   `crew-review-findings.py` and counted separately. Nits never compete with a severity finding for a
   slot: fill severity slots first, then add nits within their own budget, and drop the rest. Read the
   numbers there rather than copying them into another file.
4. Zero findings is valid. No action plan, no padding. `### Reviewers` always names how each package
   was delivered, and adds a lens with its gap only when a persona failed, was truncated, or returned
   partial coverage.
5. Per-finding length: snippet, then two or three sentences of explanation, then a one- or two-sentence
   fix or a code block. Every sentence adds information.
6. In idea and spec reviews, `Fix:` is required on every `[blocking]` and `[concern]` finding, specific
   enough to apply mechanically.
7. `kind`, `confidence`, `evidence`, and `validation` are required, not recommended: every finding
   states what sort of defect it is, how sure you are of it (the 1-5 scale in the shared contract),
   where it is, and — when `verified: true` — the one-sentence conclusion the check reached.
   `normalize` and `persist` reject a finding with no `kind` or no `confidence`, and a verified
   finding with no `validation`, so a missing field costs a round trip. Mark a finding unverified
   rather than guessing a validation line, and cite the location you actually read.

## Code review

Each finding is a self-contained GitHub PR comment body, ready to paste inline without editing. One
flat numbered list with an inline severity label — never severity headings. The label carries the
score: `[attention · 4]`. The `· <kind>` slot is separate and optional: include it when the finding
clearly fits a `KINDS` value, omit it rather than inventing one. The label is never optional, and the
score is never omitted for a finding that has one.

The report body and the paste-ready comment are not the same text. The report is for the reader who
ran the review and keeps the label, the score, and the snippet; the comment on the PR is written in
your own review-comment voice (`voice.mdc`), and `persist` collects those into `comments.md` from each
finding's `comment` field (see [evidence and comments](evidence-and-comments.md) under "Paste-ready
comments").

The anchor sits inside the code span, `**\`path/to/file.ts:42\`**`, and nowhere else: the token in
that span is the one `EVIDENCE_LOCATION` matches and the one a reader can paste into a search. The
older form that put the line number outside the span is retired, because the token a gate looks for
was hidden from the reader who wanted to search it.

````
## Review: <mode> — <summary>

1. [blocking · 4] **`path/to/file.ts:42`**

```lang
<2-5 lines anchoring the finding>
````

<What the code does wrong and why it breaks. 2-3 sentences.>

Fix:

```lang
<concrete fix when the fix is unambiguous — omit otherwise>
```

---

2. [attention · 3] **`path/to/file.ts:88`**

```lang
<2-5 lines, recommended>
```

<What to address and why. 2-3 sentences.>

Fix: <text description, or code block when concrete>

---

3. [needs more info · 2] **`path/to/file.ts:140`**

```lang
<relevant lines>
```

<Question with stated stakes — what you need to know and what breaks if the assumption is wrong.>

---

4. [nit · 5] **`path/to/file.ts:201`** — <what to change, one line>

```

## Idea and spec review

Tone is evaluative — "does this hold up?". Findings address whether the idea, plan, or reasoning is
sound.

```
## Review: Idea — <summary>

**Verdict:** proceed / revisit / blocked — <1 sentence: the decisive reason>

1. [blocking · 4] **<title>** — <what assumption breaks or what is fundamentally missing>. <why it matters>.
   **Fix:** <exact change — what sentence/section to add, remove, or reframe. Specific enough for mechanical application.>
2. [concern · 3] **<title>** — <what weakens the plan>. <why it matters>.
   **Fix:** <what would strengthen it — specific framing or addition.>
3. [needs more info · 2] **<title>** — <what is unclear and must be resolved before moving forward>.
4. [nit · 5] **<title>** — <minor framing or completeness improvement>.
```

Both artifact kinds carry the score in the label, so a spec or idea review's findings survive
`persist` exactly as a code review's do; `[concern]` sits where `[attention]` would, at any score.

With no findings, state the verdict as `proceed` and give one sentence of reasoning.

## Discipline

- No extra structure: no sub-sections, no thematic groupings, no preamble. A flat numbered list.
- Be opinionated. Surface what matters most, not everything found; a short focused report beats an
  exhaustive one.
- Never emit a finding you cannot anchor to a specific file location (code review) or a specific claim
  in the artifact (idea review).
