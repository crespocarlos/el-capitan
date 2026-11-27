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

Write the changed-path list in the same step, because nothing downstream can reconstruct it from the
packages and the `--files` gates need it:

```bash
~/.agent/bin/crew-diff.sh --name-only > "$REVIEW_ROOT/paths.txt"   # self, changes
~/.agent/bin/crew-pr-actions.py diff --pr <n> --repo <owner/repo> --name-only \
  > "$REVIEW_ROOT/paths.txt"                                        # PR
```

`paths.txt` is that command's stdout, one path per line; no other step writes it.

**Record what this round read, and name the earlier one.** Two rounds of uncommitted work can share a
`HEAD`, so `Reviewed at:` cannot tell them apart; the manifest is the per-file content id that can.
Run it in the same step, after `paths.txt`, in diff modes only — a PR review has no task-level round
to compare against:

```bash
~/.agent/bin/crew-review-findings.py prior-review --review-dir "$REVIEW_ROOT" \
  --repo "$(~/.agent/bin/crew-repo-info.py --field root)" --paths $(cat "$REVIEW_ROOT/paths.txt")
```

It prints `{"prior": "<dir>"|null, "unchanged": [...], "files": N}` and writes
`$REVIEW_ROOT/manifest.json`. Carry `prior` into `assemble.json` as `prior_review_dir`, so every
package gains the earlier round's findings under `## Already reported in an earlier round`. That block
is what stops a reworded re-raise: two measured rounds shared zero finding fingerprints and still
raised the same subject twice.

`prior: null` on a first review is a success, not a gap — say nothing about it. An `unchanged` list
larger than half the changed files is what makes `--since-last-review` worth offering; carry it in the
report's `### Reviewers` line so the reader knows the collapse ran and what it omitted.

`hunks.json` holds the ids the coverage gate checks, `hunks.md` the index plus bodies for the mapping
pass only, `hunks.index.md` the index alone for persona packages, and `package.diff` the diff with
each generated file's hunks collapsed to one note line. Packages embed `package.diff`, never
`diff.patch`. With `--since-last-review --reviewed <prior>/manifest.json`, `crew-review-hunks.py`
also collapses every file whose bytes the earlier round already read, naming its ids in the note;
that flag is opt-in because a hunk unchanged since the last round can still be newly wrong.

Dispatch `reviewer-layers` with `hunks.md`, extract its one fenced `json` block, and write that raw
JSON to `$REVIEW_ROOT/layers.json`. No block, several blocks, or any text outside the block is invalid
output. Validate the block by parsing it before anything packages it:

```bash
~/.agent/bin/crew-review-findings.py check-map "$REVIEW_ROOT/layers.reply.md" \
  --output "$REVIEW_ROOT/layers.json"
```

Save the reply verbatim as `layers.reply.md` first, then let the command parse and write the map. It
fails on a stray comma inside the fence, which coverage would otherwise report only after every
persona had run, and which a hand-repair before writing would hide entirely. On failure re-dispatch
`reviewer-layers` once with the parser's error text. It reports no findings and is not a persona, so
never add it to `--personas`. In PR mode the diff comes only from `crew-pr-actions.py diff`, which
reads the PR head over the network and never the local checkout.

Check the map before any persona runs: `crew-review-findings.py coverage --hunks
"$REVIEW_ROOT/hunks.json" --layers "$REVIEW_ROOT/layers.json"`. On failure, re-dispatch
`reviewer-layers` once with the error text; if it still fails, delete `layers.json`, continue without
a map, and name the gap in the report.

**A map assertion must be grounded in its own hunks.** `reviewer-layers` sees hunk bodies and no
repository, so an explainer naming a config key, a dependency, or a file the diff does not touch is a
guess that three personas then restate as a `[needs more info]`. When reading the map, drop any
explainer or `hunkNotes` claim its hunks do not show, and when reviewing a map that reached a real
run, verify such a claim against the diff before quoting it.

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
docstring — read it at `.agent/tools/review/crew-assemble-packages.py` in the repository, or through
`readlink -f ~/.agent/bin/crew-assemble-packages.py` when the repository is not the working tree.
`~/.agent/bin` holds symlinks, so a search tool scoped there finds nothing.

Two settings keep the size honest. The prompt tier elides the regions `package.diff` already quotes
and keeps every unchanged line, so a rule that collides with surrounding text stays visible.
`guidance_keep` narrows repository guidance per lens — `Testing` and `Verification pattern` to Code
Quality, `File layout` and `Symlink rules` to Architecture — because every lens otherwise pays for the
whole file. A prefix matching no section fails the run and lists the available ones.

## The PR-head excerpt pass

`mode_kind: "pr"` refuses `consumers` and `prompt_files`, and it is right to: both come from the local
git index, which PR mode forbids. But something has to replace them, or a PR persona receives a diff
with three context lines and no way to ground a claim about a function's scope, a consumer, or an
absence. Nothing did, and the refusal's own message — "fetch those excerpts at the PR head" — named a
step no file specified.

After `crew-assemble-packages.py "$REVIEW_ROOT"` succeeds, **append the PR-head excerpts to each
`<persona>.in.md` before `check-packages`**, under a heading that says where they came from:

```bash
mkdir -p "$REVIEW_ROOT/head"
gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>" --jq .content \
  | base64 --decode > "$REVIEW_ROOT/head/<slug>.txt"
```

Create the directory first, once, before the first fetch: the redirect does not create it, and a
missing directory turns one setup omission into a failed network read per excerpt.

Read at the head SHA the run resolved once, never at the local checkout, and label every excerpt
`path:line@headSHA7` as the PR-mode evidence rule requires. What to fetch is the same material the
refused extras would have supplied, scoped to the files the diff touches: Tier 1's surrounding lines
and signatures, Tier 2's enclosing function, Tier 3's consumers, and any file a finding's claim turns
on. Fetching is per claim, not per file set — a diff-only review of a 54-hunk PR does not need every
file opened, and a review whose findings are all nits needs almost none.

Write the appended block with the edit or write tool, then run `check-packages`. An excerpt pass that
fails leaves the package exactly as assembled, which is weaker evidence but not a broken package: say
so in `### Reviewers` as a gap, since a persona that returns `[needs more info]` naming an unfetched
path is reporting this pass, not a defect in the PR.

## Why the tool, not the hand

The tool writes the shared contract, mode block, hunk reference and memory first, then
`package.diff` in full, then the per-persona material — size gate, spec, reading map, guidance,
prior-round block, consumers, and prompt extras — in one fixed order, listed in
[context tiers](context-tiers.md#package-section-order). The shared head and the diff come first
because every persona receives them byte for byte: a harness that caches a prompt prefix then pays
for them once per run instead of once per persona. A subagent loads only its own
persona file, so a rule living in a reference file reaches it only if the package carries it.
Composing by hand is how one run delivered a reviewer a prebuilt header instead of the contract, and
`check-packages` passed anyway, because it checks the rules whose absence is detectable rather than
that two reviewers read the same evidence. `evals/tools/test_assemble_packages.py` checks that every
package opens with the same contract and hunk reference.

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
