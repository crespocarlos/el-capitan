# Package assembly and dispatch evidence

Step 5–6 detail for `crew-reviewer`. The tool owns composition; this file says what to write, what
to check, and how the evidence reaches a persona.

## Layer map (diff modes only)

```bash
# self: ~/.agent/bin/crew-diff.sh > "$REVIEW_ROOT/diff.patch"
# changes: git diff --cached > "$REVIEW_ROOT/diff.patch"
# PR: ~/.agent/bin/crew-pr-actions.py diff --pr <n> --repo <owner/repo> > "$REVIEW_ROOT/diff.patch"
python3 ~/.agent/bin/crew-review-hunks.py "$REVIEW_ROOT/diff.patch" --out "$REVIEW_ROOT"
```

`hunks.json` holds the ids the coverage gate checks, `hunks.md` the index plus bodies for the mapping
pass only, `hunks.index.md` the index alone for persona packages, and `package.diff` the diff with
each generated file's hunks collapsed to one note line. Packages embed `package.diff`, never
`diff.patch`.

Dispatch `reviewer-layers` with `hunks.md`, extract its one fenced `json` block (without the
backticks), and write that raw JSON to `$REVIEW_ROOT/layers.json`. No block, several blocks, or any
text outside the block is invalid output. It reports no findings and is not a persona, so never add it
to `--personas`. In PR mode the diff comes only from `crew-pr-actions.py diff`, which reads the PR
head over the network and never the local checkout.

Check the map before any persona runs: `crew-review-findings.py coverage --hunks
"$REVIEW_ROOT/hunks.json" --layers "$REVIEW_ROOT/layers.json"`. On failure, re-dispatch
`reviewer-layers` once with the error text; if it still fails, delete `layers.json`, continue without
a map, and name the gap in the report.

If `crew-review-hunks.py` exits non-zero the diff is empty or malformed: report it and continue
without a map. Personas then get their normal size-gated package with no `## Reading map` section.
Without `layers.json`, `persist` skips the coverage gate and warns when `hunks.json` exists,
so an unmapped review is never silent; with one, any hunk left out is rejected, so a map is never
partially applied.

## Hunk reference

When `hunks.json` exists, append each id, file, and changed-line range from `hunks.index.md` — never
the `hunks.md` bodies, which re-quote a diff the package already holds — under `## Hunk reference`,
paired with the hunk-citation sentence the packaging rules require (see
[context tiers](context-tiers.md)). Without a Reading map the index imposes no reading order, but the
heading plus that sentence is what lets every persona cite the ids `persist` requires, in the
`path:line (h7)` form the rest of the pipeline reads.

## assemble.json

Write `$REVIEW_ROOT/assemble.json`, then run `~/.agent/bin/crew-assemble-packages.py "$REVIEW_ROOT"`.
Keys: `repo` (path), `mode` (a markdown block), `size_gate` (one line), `consumers` (`[[path, start,
end, label], …]`), `prompt_files` (`[path, …]`), `guidance_keep` (`{persona: [level-2 heading prefix,
…]}`, optional), and `mode_kind` (`"pr"` when the review reads a PR head, which refuses `consumers`
and `prompt_files` because those would come from the local checkout). Exact shapes: the tool's
docstring.

Two settings keep the size honest. The prompt tier elides the regions `package.diff` already quotes
and keeps every unchanged line, so a rule that collides with surrounding text stays visible.
`guidance_keep` narrows repository guidance per lens — `Testing` and `Verification pattern` to Code
Quality, `File layout` and `Symlink rules` to Architecture — because every lens otherwise pays for the
whole file. A prefix matching no section fails the run and lists the available ones.

## Why the tool, not the hand

The tool writes the shared contract, mode block, hunk reference, guidance, memory, spec, reading map,
`package.diff`, and the consumer and prompt extras in one fixed order. A subagent loads only its own
persona file, so a rule living in a reference file reaches it only if the package carries it.
Composing by hand is how one run delivered a reviewer a prebuilt header instead of the contract, and
`check-packages` passed anyway, because it checks the rules whose absence is detectable rather than
that two reviewers read the same evidence. The eval harness composes the same contract
(`load_persona_prompt` in `evals/reviewer/run.py`), which keeps the measured prompt and the dispatched
prompt the same shape.

In spec and idea reviews there is no diff, so the tool does not apply: compose by hand in the same
order, contract first.

## ES|QL / Elasticsearch docs trigger

Every persona already carries the docs rule from `~/.cursor/agents/references/reviewer-contract.md`
(search with `search_internal_docs`, confirm with `get_internal_document_by_url`, mark `unverified`
when unavailable). The trigger only tells the persona this artifact needs it. When the reviewed
content contains ES|QL (`FROM … |` queries, `.esql` files, `esql` identifiers) or Elasticsearch/Kibana
API claims, add to every persona's package: "This artifact contains ES|QL or Elasticsearch API claims.
Verify the syntax, function availability, and API behavior with the docs MCP server before reporting,
and cite the URL. State `unverified` when the docs are unreachable." Every reviewer persona and
`reviewer-explorer` holds the docs server's search and fetch-by-URL tools, so the check stays possible
whenever that server is configured.
