# Review: reviewer persona improvements + eval harness

**Mode:** self (staged changes)  
**Diff:** 18 files, 924 insertions, 110 deletions  
**Strategy:** full review (≤5000 lines)  
**Spec:** Reviewer eval harness (status: done)  
**Reviewers:** Code Quality, Architecture, Product Flow, Fresh Eyes, Adversarial (≥100 lines ✓), Prompt Quality (agent/skill files ✓)  
**Explorer:** dispatched (4 new files)

---

## [blocking]

**1. `score_finding_match` — label and hint checked across full output, not per-finding** (also flagged by: Code Quality)

> "`score_finding_match` requires BOTH `[{severity}]` label AND `match_hint` substring present in output"

If a review contains `[blocking]` for one finding and the word "null dereference" in a separate, unrelated paragraph, fixture r1 scores as a match — recall is falsely inflated and the harness cannot distinguish correct detection from accidental co-occurrence.  
Fix: Scope both checks to the same line or finding block (e.g., split `raw_output` on newlines, require both substrings in the same entry).

---

## [attention]

**2. `compute_precision_recall` — precision can exceed 1.0 when expected findings share label+hint**

> `precision = len(matched) / label_count`

If two expected findings both pass `score_finding_match` against the same single label occurrence, `len(matched) = 2` but `label_count = 1`, yielding precision = 2.0 — an invalid value that silently corrupts the summary table.  
Fix: Cap with `precision = min(len(matched), label_count) / label_count`, or deduplicate matched findings against distinct label occurrences.

**3. `_run_one` — shared mutable set mutated from worker threads**

> `all_personas.add(persona_name)` inside `_run_one`

`all_personas` is a `set` defined in `main()` and mutated concurrently by up to 6 threads with no synchronization; CPython's GIL makes individual `set.add` calls incidentally safe today, but this is an undocumented assumption that breaks under PyPy or if the closure is refactored.  
Fix: Remove the mutation from `_run_one`, return `persona_name` in the result dict, and populate `all_personas` in the main-thread result collection loop.

**4. `load_output_rules` — first backtick-fence inside the rules block truncates extraction**

> `re.search(r'(Produce your review now\..*?)```', text, re.DOTALL)`

Non-greedy match stops at the first ` ``` ` after the marker; if the output rules contain an inline code fence (e.g., a label format example), extracted rules are silently truncated with no error raised.  
Fix: Match the closing fence with a line-anchored pattern (e.g., `` r'```\s*$' `` with `re.MULTILINE`) or extract to end-of-section instead.

**5. Explorer trigger decoupled from Architecture signal** (Architecture)

> "changed from 'Architecture signal fired (new files OR new exports)' to 'new files present only'"

Architecture reviewer previously acted as the integration point that requested richer context when it detected structural change (new exports); removing that coupling means refactors that add no new files but change exported contracts will run Architecture without the module-graph context it needs.  
Fix: Add "OR new exports detected in diff" as a secondary Explorer trigger, independent of which persona fired.

**6. `summarize()` — "fixtures" column header counts only precision-eligible runs** (Fresh Eyes)

> `{'fixtures':>8}` in the printed table; value is `s["fixtures_run"]` which excludes truncated and no-expected-findings runs

A first reader of the printed table will assume the number is total fixtures executed, not a filtered precision-eligible subset, making scores look better-covered than they are.  
Fix: Rename the column to `scored` or `valid`.

**7. Adversarial skip is invisible to engineer** (Product Flow)

> "Adversarial reviewer now only runs when diff ≥100 lines. On small diffs, the engineer gets no adversarial review."

The engineer receives the same consolidated output format whether Adversarial ran or not — there is no signal in the review output that the adversarial pass was skipped, so they cannot compensate for the gap.  
Fix: Add a one-line notice in the review output when Adversarial is suppressed (e.g., "Adversarial skipped — diff below 100-line threshold").

**8. `reviewer-prompt-quality.md` — opening line contradicts persona scope** (Prompt Quality)

> "The artifact may be a code diff, a plan, a design proposal, or a session discussion."

Frontmatter says "Works on agent/skill/prompt file diffs" but the opening preamble accepts any artifact type, which will cause the model to apply prompt-quality analysis to code or design docs outside its lane.  
Fix: Replace opening line with "The artifact is a diff or content of agent, skill, or prompt files (system prompts, instructions, `*.prompt.md`, `instructions.md`, etc.)."

**9. `reviewer-prompt-quality.md` — `model: inherit` without resolution triggers its own rule** (Prompt Quality)

> "Flag when a prompt uses patterns that work on one model family but degrade on another, especially if the config specifies `model: inherit` without clarity on what model that resolves to."

The persona uses `model: inherit` with no note resolving what that inherits from — the model-compatibility section will flag its own config when a self-review runs through this persona.  
Fix: Add a frontmatter comment or inline note specifying what `inherit` resolves to in the dispatch context.

---

## [needs more info]

**10. Two eval harnesses with divergent concurrency models** (Architecture)

> "evals/run.py: TaskGroup pattern (async) … evals/reviewer/run.py: ThreadPoolExecutor (sync)"

If these harnesses are expected to be composed (e.g., a top-level `evals/run_all.py`), mismatched concurrency models will make that composition non-trivial; if intentionally standalone, the divergence is harmless.  
Fix/Response: Clarify whether a shared eval runner is planned — if yes, align concurrency models now; if no, document the standalone boundary explicitly in `evals/README.md`.

**11. `crew-address-review` — "all" approval response semantics conflict with pre-populated verdicts** (Product Flow)

> "Which fixes should I apply? (all / none / comma-separated numbers)"

The verdict table pre-populates agent verdicts (Apply, Reject, Already Addressed) and then asks for "all" — it is undefined whether "all" means "apply every numbered row regardless of pre-verdict" or "apply only Apply-verdicted rows"; if the former, the engineer unknowingly reverses an agent rejection.  
Fix/Response: Clarify in the prompt whether pre-verdicts are advisory or binding, and rename "all" to reflect what it actually does (e.g., "all approved" if it only applies Apply-verdicted rows).

---

## [nit]

**12. `evals/reviewer/run.py` — magic token-price literals** (Code Quality)

> `cost_approx = (total_input * 15 + total_output * 75) / 1_000_000`

Prices are inlined without names, silently stale when pricing changes or a different model is used.  
Fix: Define `OPUS_INPUT_PRICE_PER_MTOK = 15` and `OPUS_OUTPUT_PRICE_PER_MTOK = 75` as module-level constants.

**13. `reviewer-product-flow.md` — bail-out parenthetical not updated** (Fresh Eyes)

> "(pure refactor, internal type changes, config-only diff)"

The parenthetical still only illustrates the "no user-facing surface" trigger; the new "no spec is provided" condition has no example, making it feel like an oversight.  
Fix: Append a no-spec example, e.g., add "or any change where no spec was provided" to the parenthetical.

---

## Reviewers

| Reviewer | Status | Word count |
|---|---|---|
| Adversarial | ✓ | ~200 |
| Code Quality | ✓ | ~250 |
| Architecture | ✓ | ~220 |
| Fresh Eyes | ✓ | ~180 |
| Product Flow | ✓ | ~210 |
| Prompt Quality | ✓ | ~190 |
| Explorer | ✓ | ~310 |

Explorer note: No duplication or conflicts detected. New `reviewer-prompt-quality.md` follows the established persona convention. `evals/reviewer/` is a clean separation from the existing `evals/run.py` three-arm harness.

*(spine-focused not applied — diff ≤5000 lines, all 18 files reviewed)*
