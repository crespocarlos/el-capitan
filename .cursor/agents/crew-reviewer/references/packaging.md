# Package assembly and dispatch evidence

Step 5–6 detail for `crew-reviewer`. The tool owns composition; this file says what to write, what
to check, and how the evidence reaches a persona. `REVIEW_ROOT` is the review directory.

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
repository, so an explainer about anything outside them is a guess that three personas then restate
as a `[needs more info]`. When reading the map, drop any
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
…]}`, optional), `questions` (`{persona: [question, …]}`, below), and `mode_kind` (`"pr"` when the
review reads a PR head, which refuses `consumers` and `prompt_files` because those would come from the
local checkout). Exact shapes: the tool's
docstring — read it at `.agent/tools/review/crew-assemble-packages.py` in the repository, or through
`readlink -f ~/.agent/bin/crew-assemble-packages.py` when the repository is not the working tree.
`~/.agent/bin` holds symlinks, so a search tool scoped there finds nothing.

Two settings keep the size honest. The prompt tier elides the regions `package.diff` already quotes
and keeps every unchanged line, so a rule that collides with surrounding text stays visible.
`guidance_keep` narrows repository guidance per lens — `Testing` and `Verification pattern` to Code
Quality, `File layout` and `Symlink rules` to Architecture — because every lens otherwise pays for the
whole file. A prefix matching no section fails the run and lists the available ones.

## Questions for each lens

Every package ends with `## Questions for this lens`: 2 to 5 questions you write for that persona from
the diff and the spec's risks. Each names a concrete input, path or claim and asks what happens, in the
persona's lens: an input that breaks the change (Adversarial), the approach against its alternatives
and a consumer (Architecture), the user's next step (Product Flow), a rule that collides or fires
too late (Prompt Quality), a test a wrong implementation would pass (Code Quality). A question the
diff answers wastes the budget.

Diff modes put them in `assemble.json` `questions`; the tool renders them last, after the evidence,
and stamps the run in `manifest.json`. Spec and idea packages append them by hand. `check-packages`
refuses a stamped package without the section, or with other than 2 to 5 unindented list items under
its last copy; an unstamped directory passes with a note.

## Why the tool, not the hand

The tool writes the shared contract, `lookups.md`, mode block, hunk reference and memory first, then
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
order, the contract (`reviewer-contract.md`, one blank line, `reviewer-reads.md`) and `lookups.md`
first. A PR review appends the head excerpts ([PR review mode](pr-mode.md)).

## The reply marker

Before each dispatch, in Claude Code and Cursor, the probe included (a claim-check
`reviewer-explorer`: its own `claims/<n>` directory, [consolidation](consolidation.md)), run
`~/.agent/bin/crew-review-findings.py expect --review-dir "$REVIEW_ROOT" --persona <persona>` and
make the line it prints the first line of the dispatch prompt, unchanged. It writes
`<persona>.expect` with a random nonce; the subagent-stop hook saves each reply whose marker carries
that nonce ([dispatch](~/.cursor/agents/references/dispatch.md) says which reply counts). With a
task, the next line is `crew-task: <TASK_DIR>`, so the hook records the persona's usage on it.
