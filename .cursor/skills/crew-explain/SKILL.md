---
disable-model-invocation: true
name: crew-explain
description: "Build a layered reading map for a PR: what to read in what order, why each layer exists, and where to look closely. Trigger: 'crew explain PR #X', 'crew explain <URL>', or 'crew explain' for the current branch's PR."
---

**Workflow**: review | **Stage**: pre-PR assist

# Layered PR explainer

Produces a reading map for a human reviewer: the diff regrouped into layers that can be read
bottom-up, each with an explainer and a focus list. It never posts to GitHub and never changes the PR;
the map is rendered in chat.

Self-contained. The hunk parser is `crew-review-hunks.py` and the validator is `crew-review-findings.py
validate-map`, both in this repository, so no external checkout has to be installed for a map to exist
or to be checked.

## Execution model

Single-shot, one pass: resolve, fetch, map, validate, render. No progress narration.

## Step 1: resolve the PR

```bash
gh pr view ${1:+"$1"} --json number,url,title,body,author,baseRefName,headRefName,headRefOid,labels,isDraft
gh repo view --json nameWithOwner
```

`crew explain` with no argument uses the current branch's PR. Record `owner/repo` and the immutable
`headRefOid`; everything read afterwards is at that SHA.

## Step 2: build the hunk index

```bash
WS="/tmp/crew-explain-$(basename "$(pwd)")-<number>"
mkdir -p "$WS"
gh pr diff <number> -R <owner/repo> > "$WS/pr.diff"
python3 ~/.agent/bin/crew-review-hunks.py "$WS/pr.diff" --out "$WS"
```

A non-zero exit means the diff is empty or is not a unified diff; stop and report it, because there is
nothing to map. Write the PR metadata to `$WS/pr.md` alongside `hunks.md` so the mapping pass gets
both the index and the PR's stated intent.

## Step 3: map the diff into layers

Read `$WS/hunks.md`. Group every hunk into layers a reviewer can read in order, using only the layer-building rules in
[reviewer-layers](~/.cursor/agents/reviewer-layers.md) ("How to build layers" and its guidelines):
bottom-up order (foundation, core, prompts, wiring, surface, tests, mechanical), 1–8 layers, each with an
`explainer` (what changes and why, how it connects to the previous layer) and a `reviewFocus` (what
deserves scrutiny — edge cases, invariants, ordering, compatibility, error paths). Step 4 owns the
output contract, including `summary`, `risk`, `concerns` and `references`; ignore that file's "no
findings" and single-json-block output rules, which belong to the review pre-pass.

Research where it pays off, and prefer primary sources over guessing:

- File contents at the head: `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>"`, one quoted
  literal command per read. List the parent (`--jq '.[].name'`) instead of guessing a path from a
  symbol name.
- Usages of a changed API, existing review comments, and linked issues: `gh search code`, `gh pr view
  --comments`, `gh issue view`.
- Elastic/Kibana and ES|QL claims: verify against a docs MCP server when one is configured. State
  `unverified` when none is available.

Reads are PR-head only. Never `gh pr checkout`, fetch the PR ref, or read the local checkout to build
context: it is not at the head.

## Step 4: write and validate the map

Write `$WS/review.json`:

```json
{
  "summary": "markdown: 3-6 sentences on what the PR does and how to approach reviewing it",
  "context": "markdown (optional): background, linked issues, prior art",
  "risk": "low | medium | high",
  "layers": [
    { "id": "foundation", "kind": "foundation", "title": "…", "explainer": "…",
      "reviewFocus": "- …", "hunks": ["h3", "h1"], "hunkNotes": { "h3": "…" } }
  ],
  "concerns": [{ "severity": "medium", "title": "…", "detail": "…", "hunk": "h7" }],
  "references": [{ "title": "…", "url": "https://…", "why": "…" }]
}
```

Every markdown field is a JSON string, so bullets live inside the string with `\n`, never as a JSON
array. Then:

```bash
python3 ~/.agent/bin/crew-review-findings.py validate-map --review "$WS/review.json" --hunks "$WS/hunks.json"
```

It reports each problem with its layer index — an unassigned hunk, an unknown or duplicated id, a
missing explainer, an invalid severity — and exits non-zero. Fix and re-run, at most twice; after that
report the remaining errors instead of looping. A map that validates here also passes the coverage
gate in `crew review`, because both use the same checker.

## Step 5: render

Print the map in chat. Do not post it anywhere.

```markdown
## Reading map: <title> (#<number>)

<summary>
Risk: <risk>. <n> layers, <m> hunks. Head: `<sha7>`.

### 1. <layer title> (<kind>)
<explainer>

Focus:
<reviewFocus bullets>

Hunks: `h1` `h4` — `path/a.ts` (+12/-3), `path/b.ts` (+4/-0)

### Concerns (from the mapping pass)
- [<severity>] <title> — <detail> (`h7`)

### Coverage
<m>/<m> hunks mapped.
```

Label the concerns as mapping observations, not review findings: they come from this pass, not from a
persona, and `crew review` is still the gate.

## Rules

- Read-only toward GitHub and toward local clones.
- Never post a comment, review, or label.
- Never invent a hunk id; `validate-map` rejects one.
- A hunk that is hard to place still gets a layer. Leaving it out is the one failure that looks like
  success, because the map then reads as complete.
