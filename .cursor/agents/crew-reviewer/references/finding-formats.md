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
7. `verified: true` requires a one-sentence `validation` saying what the check read and what it
   concluded. `normalize --strict` rejects a verified finding without it, so a missing sentence costs a
   round trip. Mark a finding unverified instead of guessing a validation line.

## Code review

Each finding is a self-contained GitHub PR comment body, ready to paste inline without editing. One
flat numbered list with an inline severity label — never severity headings. The `· <kind>` slot after
the label is optional: include it when the finding clearly fits a `KINDS` value, omit it rather than
inventing one; the label itself is never optional.

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

## Idea and spec review

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
```

With no findings, state the verdict as `proceed` and give one sentence of reasoning.

## Discipline

- No extra structure: no sub-sections, no thematic groupings, no preamble. A flat numbered list.
- Be opinionated. Surface what matters most, not everything found; a short focused report beats an
  exhaustive one.
- Never emit a finding you cannot anchor to a specific file location (code review) or a specific claim
  in the artifact (idea review).
