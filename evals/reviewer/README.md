# Reviewer eval

Measures how often each reviewer persona and spec critic catches a known defect. Each case is a
small diff (or a small spec, for the critics) that hides one defect a real review found, labelled
with the lens that should catch it.

## Layout

| Path | Contents |
| --- | --- |
| `build_cases.py` | The source of the in-sample cases (the ones the persona rewrite was tuned against); edit a case there, run it, and commit both |
| `build_heldout.py` | The source of the held-out cases, written blind to the rewrite: `python3 evals/reviewer/build_heldout.py evals/reviewer/cases` |
| `cases/<id>/case.json` | Generated: the lens, the source, the change summary the persona reads, the hidden defect, where it is (`locations`, and `refs` for a spec), the keyword groups, the unchanged files (`context`) and the changed files after the change (`after`) |
| `cases/<id>/change.diff` or `spec.md` | Generated: what the persona reviews |
| `score.py` | Scores recorded replies; offline, no model call |
| `live.py` | The live run (opt-in, spends): dispatches personas and records their replies |
| `recorded/<label>/<persona>/<case>/run-<n>.md` | One reply per run, with `run-<n>.meta.json`: the exit code, the scratch root's name (`scratch`), tainted paths, paths outside the root whose call failed (`outside_failed`), every tool call (`calls`: its name, the path relative to the case root or the pattern it was given, and `error` when its result was an error) and the session's `num_turns`, so a run can be audited |
| `recorded/sample/` | Hand-written fixtures for the scorer's tests, not model output |

**Sources.** Cases are reduced from the persisted reviews and specs under `~/.agent/tasks/` (the task
and review are named in `source`), keeping only el-capitan code. A case with no persisted finding to
draw on, such as every critic case (critic replies are not persisted), is written by hand and says
`hand-seeded` in `source`. Nothing from another repository is copied; a defect seen elsewhere is
rebuilt as a synthetic equivalent and marked hand-seeded. A test checks that each `change.diff` agrees
with the case's `after` files line for line.

## Scoring

A run catches a case when one finding in the reply both:

- **anchors at the defect:** a `path:line` within 5 lines of one of the case's `locations` (an absolute
  or partial path counts). A range wider than 10 lines points at a region and locates nothing. For a
  spec case, a line number near a location, or one of the case's `refs` on the finding's first line,
  also counts;
- **names it:** every keyword group matches the finding's prose, with fenced and inline code removed
  (a quote of the change is not a description of what is wrong with it), as a whole word,
  case-insensitive. A trailing `*` makes a keyword a prefix. No group holds a word any finding could
  contain (`score.GENERIC_TERMS`), and a spec case has a second group naming the specific thing. A
  hand-seeded design case, whose defect names a better approach, sets `"match_code": true` in
  `case.json`: a design reply names its mechanism in backticks, so for that case code counts too.

Findings start at a severity label (the reviewer contract) or a bold reference followed by a dash (the
critic contract). The last one ends at the blank line after its `Fix:` paragraph, or at a `Verdict:`
line, a heading or a `Files` line, so closing remarks are no part of it.

A persona's rate in one run is the share of its own lens's cases it caught. Its mean is over the runs,
reported with each run's rate and the spread, so the variance is visible. A missing reply and a tainted
run (one that touched a path outside its case) count as misses and are listed.

The rate is recall only, so a persona that sprays findings would score higher. Next to the mean, each
persona's line shows two means over the replies recall scores (failure records and tainted runs are
left out): findings per reply, and unmatched findings per reply, those anchored at none of the case's
locations. A critic finding is located by the criterion, task or section its bold reference names (one
of the case's `refs` anywhere on its first line); a `SPEC.md:N` near the defect also counts, though the
critic's spec is not numbered, so no line is required.

**The bar for a rewritten persona** (`score.py <run> --against <baseline>`, exit 1 when it fails, exit 2
when the baseline is not a directory or holds no replies): the candidate has at least the baseline's
number of runs, its mean is at least the baseline mean minus one baseline run's spread, it catches
every case the baseline caught in all of its runs, and, unless its mean rises by more than one baseline
spread, its unmatched findings per reply stay within `max(baseline × 1.5, baseline + 0.5)`
(`NOISE_GROWTH`, `NOISE_FLOOR`), so a clean baseline does not demand zero noise. The comparison
prints both counts, baseline and candidate, per persona (`noise` in `--json`).

## Running

```bash
python3 evals/reviewer/score.py evals/reviewer/recorded/<label>            # score a recorded run
python3 evals/reviewer/score.py evals/reviewer/recorded/<new> --against evals/reviewer/recorded/<baseline>
python3 evals/reviewer/live.py                                              # the plan only: dispatches nothing
```

**The owner's baseline run** (opt-in: 24 cases x 3 runs = 72 persona sessions on the harness's model and
account; refused under `CI`; never run by the test suite):

```bash
python3 evals/reviewer/live.py --yes-spend --label baseline-$(date +%F)
```

The plan line says how many replies are already recorded and how many it will dispatch: a re-run with
the same label skips every `run-<n>.md` that holds a reply (`--redo` dispatches them again), and the run
stops with exit 3 after 3 failed dispatches in a row. A failed record keeps whatever the harness printed.

## Isolation

Each dispatch runs in a fresh scratch directory holding only the case's files, with the package on stdin:

```bash
claude -p --restricted --strict-mcp-config --disable-slash-commands --tools Read,Grep,Glob \
  --permission-prompts none --no-session-persistence --output-format stream-json --verbose \
  --agents '{"reviewer-<lens>": {"description": …, "prompt": <the persona file body>, "tools": ["Read", "Grep", "Glob"], "maxTurns": N}}' \
  --agent reviewer-<lens>
# environment: CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
```

The persona is defined from its source file in `.cursor/agents/`, not the installed copy, so it gets no
MCP servers. The package is the one a real run sends (the reviewer contract and the mode, or the critic
dispatch and contract), except that the lookups paragraph is replaced by one line: no code index or docs
server in this eval; use Read, Grep and Glob on the case files.

**What `claude --help` confirms:**

- `--restricted` ignores the user, project and local settings files, and confines the file tools to the
  working directories;
- `--strict-mcp-config` without `--mcp-config` loads no MCP server;
- `--disable-slash-commands` turns skills off;
- `--tools` limits the built-in tools.

**Not used:**

- `--bare` would skip hooks, CLAUDE.md and auto-memory, but it reads only `ANTHROPIC_API_KEY`, never the
  OAuth login.
- `--safe-mode` disables custom agents, which this run needs.

**Not confirmed:**

- whether `--restricted` also skips the user CLAUDE.md and its imports, and the hooks of plugins enabled
  outside the settings files;
- whether `--agents` honours `tools` and `maxTurns` exactly as frontmatter does.

**The backstop:** every tool call in the stream-json transcript with a path outside the scratch root,
and every `path:line` in the reply that cites one, is recorded in `run-<n>.meta.json` as `tainted`. A
tainted run is a miss. A call outside the root whose result was an error read nothing (a mistyped or
missing path), so it is recorded under `outside_failed` instead; a call whose result never arrived
counts as tainted.

## Results: Phase 3 persona rewrite (2026-11-27)

Two recordings, 3 runs of every case each (108 sessions apiece):

- `recorded/baseline-2026-11-27/`, the prompts before the rewrite;
- `recorded/after-final/`, the rewritten personas and contracts.

Two later changes are not in either recording, so neither recording measures them:

- the small wording fixes from the final prompt-quality review;
- the principal-engineer rewrite of `reviewer-architecture` (approach first, steelmanned
  alternatives, cost of the next changes, and the `Approach:` verdict).

The architecture rows below therefore describe the earlier architecture persona. The defect cases
here do not test approach judgement at all.

The cases are 24 in-sample ones (`build_cases.py`; the rewrite saw their baseline replies) and 12
held-out ones (`build_heldout.py`, written after the rewrite by an agent that never saw it). The
adversarial persona was not rewritten and has no held-out cases. The table gives mean recall
(per-run rates in brackets), then findings and unmatched findings per reply.

| Persona | Baseline, in-sample | After, in-sample | Baseline, held-out | After, held-out |
| --- | --- | --- | --- | --- |
| adversarial (not rewritten) | 0.78 [0.83 0.83 0.67] · 3.50 · 1.44 | 0.78 [0.83 0.83 0.67] · 3.50 · 1.50 | — | — |
| code-quality | 0.89 [0.67 1.00 1.00] · 3.56 · 1.11 | 0.89 [0.67 1.00 1.00] · 4.22 · 0.89 | 1.00 · 3.00 · 0.83 | 1.00 · 3.17 · 1.00 |
| architecture | 1.00 [1.00 1.00 1.00] · 2.67 · 1.11 | 1.00 [1.00 1.00 1.00] · 2.67 · 1.00 | 1.00 · 3.50 · 2.00 | 0.83 [1.00 0.50 1.00] · 3.80 · 2.20 |
| product-flow | 0.89 [0.67 1.00 1.00] · 2.33 · 1.00 | 1.00 · 2.89 · 1.00 | 0.83 [0.50 1.00 1.00] · 3.17 · 0.83 | 1.00 · 3.17 · 0.83 |
| prompt-quality | 0.67 [0.67 0.67 0.67] · 3.78 · 1.44 | 1.00 · 5.00 · 2.67 | 0.83 [1.00 0.50 1.00] · 3.33 · 2.00 | 0.83 [1.00 1.00 0.50] · 4.33 · 1.83 |
| specwriter-adversarial | 0.56 [0.33 0.67 0.67] · 5.11 · 4.11 | 0.89 [1.00 0.67 1.00] · 3.78 · 2.11 | 0.83 [1.00 0.50 1.00] · 4.83 · 2.17 | 1.00 · 4.33 · 1.33 |
| specwriter-scope | 0.89 [1.00 0.67 1.00] · 4.78 · 2.78 | 0.78 [0.67 1.00 0.67] · 4.67 · 2.89 | 1.00 · 5.00 · 3.67 | 1.00 · 4.67 · 3.17 |

**The bar** (`score.py recorded/after-final --against recorded/baseline-2026-11-27`, all 36 cases)
holds for six personas. It fails for architecture on one run, `task-review-import-cycle` run-2, which
is recorded as tainted and so counts as a miss. The reply itself catches the case.

The tainted call reads `src/crew/TOOLS.md` under a path whose last component has the run's
scratch name. Every other Read in the run was recorded relative to the root, so the root check
matched the model's working-directory form. The persona then read the same file again by its
in-root path. Together these point to a first read under a mistyped copy of the random scratch
suffix, which failed, so nothing outside the case was read. The run predates the `scratch` and
`error` fields, so this cannot be confirmed from its record, and it stays tainted.

**What the numbers can and cannot say:**

- The eval is near its ceiling, with 5 to 6 cases per lens, and it measures recall plus a coarse
  noise count. It can show a loss; it can hardly show a gain. The table is no evidence that the
  rewrite improved review quality.
- The in-sample gains are on cases the rewrite was tuned against.
- The evidence for the role changes (owners, attacks, dead areas) is the role-coverage audit,
  `~/.agent/tasks/1D001C12-07C4-4035-9E18-DF7A9E1FCE6D/artifacts/role-coverage.md`, not these scores.
- Every after reviewer reply printed the `Read beyond the package:` line the contract asks for
  (78/78); 51 of them named real reads.

### Architecture as a principal engineer (2026-11-27, later the same day)

The owner judged the architecture persona shallow: it found defects but never challenged an approach. Its 1.00 on the defect cases could not show that, so five design-challenge cases (`design-*`, hand-seeded from real approach reversals, `match_code`) were built by an agent that never saw the persona. A design case counts the keywords anywhere in a finding or in the preamble before the findings (the approach verdict), and the rule applies to every reply, old and new.

| Architecture prompt | Defect cases | Design cases | Approach verdicts |
| --- | --- | --- | --- |
| Before the rewrite (`baseline-2026-11-27`) | 15/15 | 5/15 | none |
| Principal engineer, first wording (`arch-principal`) | 15/15 | 11/15 | 29 redirect, 1 endorse |
| Principal engineer, shipped wording (`arch-principal-2`) | 15/15 | 9/15 | 25 redirect, 5 endorse |

- The first wording is the clean measurement: neither its author nor the orchestrator had seen the design cases. The shipped wording was revised after the orchestrator read the first wording's replies (verdict meanings, "what is needed" and "what exists" first), so its design numbers are not held out. 11 against 9 is within the noise of 5 cases and 3 runs.
- What the numbers support: the rewrite challenges an approach about twice as often, with no loss on defects. What they do not: how good the challenge is, since keywords only check that the better approach is named. Read a pair of replies to the same design case (for example `design-readonly-deny-list` in `baseline-2026-11-27` and `arch-principal-2`) before trusting either number.
- Open: the verdict still leans to `redirect` on defect-only cases, and the shipped wording endorsed the marker-file design in all three runs, where a built-in permission prompt was the better approach.
