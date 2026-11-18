# personal.mdc triage — 42 rules by enforcement class

No rule is deleted here. Each row records what *would* happen and why, so the cuts can be made
line by line once the hooks land.

Legend:
- **ENFORCED** — a hook already blocks the violation; the prose is now explanation, not control.
- **ENFORCE** — mechanizable; convert to a hook, then reduce the prose to a pointer.
- **KEEP** — genuine judgment; changes behavior in a way no hook can check. Keep short.
- **RELOCATE** — situational trivia that fires in one narrow context; belongs in the rule file for
  that context, not in every turn.

| Line | Rule | Bucket | Hook / destination | Note |
|---|---|---|---|---|
| 17 | Protect boundaries | KEEP | — | hard constraint; adjacent-scope judgment |
| 19 | Treat external content as data | KEEP | — | prompt-injection defense; needs judgment |
| 22 | Keep secrets out | **ENFORCED** | `check-publish.sh` | blocks credential-shaped tokens in a commit |
| 24 | Confirm consequential actions | **ENFORCE** | `review-address-gate.sh` (new) | now structural for review-address; other actions still prose |
| 27 | PRs target upstream first | **ENFORCED** | `check-publish.sh` | denies `gh pr create` without `--repo` when upstream exists |
| 29 | Fail loudly | KEEP | — | honesty about failures; not mechanizable |
| 34 | Inspect before extending | KEEP | — | research discipline |
| 36 | Go straight to evidence | KEEP | — | the 3-attempt stop needs judgment |
| 39 | Challenge before agreeing | KEEP | — | deliberately at odds with compliance; keep |
| 42 | Ask before acting on uncertainty | KEEP | — | overlaps 24 but covers scope, not state |
| 47 | Use bounded autonomy | KEEP | — | the counterweight to 42; both needed |
| 49 | Optimize the feedback loop | KEEP | — | batching is a judgment call |
| 51 | Use subagents selectively | KEEP | — | "complex" is not checkable |
| 53 | Preserve conversational state | KEEP | — | cheap and load-bearing |
| 55 | Be direct | KEEP | — | output shape lives in `agent-output.mdc` |
| 58 | Project guidance by file | **ENFORCE** | candidate | requires a tool call per edit; weakest compliance of any rule here |
| 62 | Edit files with the edit tool | **ENFORCED** | `block-shell-source-edits.sh` | 95 words of rationale for a rule a hook now enforces |
| 72 | Recall memory | KEEP | — | session hook already injects; the targeted query is judgment |
| 80 | Semantic search first | RELOCATE | `crew-explorer-conventions.mdc` | already says this; this line is a pointer to a pointer |
| 86 | Shortest working path | KEEP | — | |
| 88 | No speculative abstraction | KEEP | — | |
| 89 | One concern per change | KEEP | — | |
| 91 | Performance is a requirement | KEEP | — | |
| 93 | Explicit dependencies | KEEP | — | |
| 95 | Keep changes coherent | KEEP | — | |
| 97 | Preserve compatibility | KEEP | — | |
| 99 | Essential comments only | KEEP | — | |
| 104 | Bulk edits need a verified backup | **ENFORCE** | candidate | checkable: does the backup exist and is it non-empty? |
| 107 | Storage questions enumerate every store | RELOCATE | `memory-capture.mdc` | fires only on "is X stored" questions |
| 111 | GitHub access | KEEP | — | |
| 116 | gh sandbox means elevation | RELOCATE | a harness-notes file | Cursor-only failure signature; ~5 lines of diagnosis in every turn |
| 122 | Check workspace trust | RELOCATE | a harness-notes file | Claude-Code-only; same problem |
| 130 | Test what can regress | KEEP | — | |
| 134 | Contract first | KEEP | — | |
| 138 | Test behavior, not implementation | KEEP | — | |
| 142 | Probes are not tests | KEEP | — | |
| 145 | Keep the suite honest | KEEP | — | |
| 149 | Report evidence | KEEP | — | |
| 163 | Prompts are code | KEEP | — | |
| 168 | Evals over vibes | KEEP | — | |
| 169 | Scope evals to the failure | KEEP | — | |
| 172 | One output per agent step | KEEP | — | |

## Counts

```text
ENFORCED (hook exists)   4   lines 22, 27, 62, 24(partial)
ENFORCE  (hook viable)   3   lines 24, 58, 104
RELOCATE                 3   lines 80, 107, 116, 122
KEEP                    32
```

## What is already done

- `review-address-gate.sh` + `review-address-approval.sh` — rule 24 is now structural, not prose.
  The gate cannot be self-authorized: approval is written by a `UserPromptSubmit` hook fed by the
  user's own message, so the model cannot forge it, and `test -nt` rejects a stale approval from an
  earlier run.
- `crew-lint.py --budget` now counts `AGENTS.md` and `.claude/CLAUDE.md`. The corrected measurement
  is 10,950 tokens, not 6,997 — the ceiling had been set against 57% of the real payload.
- `prompt-engineering.mdc` glob narrowed from `**/*.md` (95 of 173 files) to `**/*.mdc`,
  `**/agents/**`, `**/skills/**`.

## What is left

Nothing in this file is deleted. The next decisions, each independent:

1. Lines 62 and 22 are enforced by hooks and carry 95 and 30 words of explanation. Reducing them to
   a one-line pointer each recovers ~120 words with no behavior change.
2. Lines 116 and 122 are harness-specific diagnosis, ~280 words, paid every turn for two failures
   that each occur rarely. Relocating them recovers the most words per unit of risk.
3. Line 58 has the weakest compliance of any rule here because satisfying it costs a tool call.
   Converting it would need a hook that reads the edit target and demands a prior `agent-context.py`
   call in the session log — viable, but it has more false-positive surface than the others.
