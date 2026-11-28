## Review artifacts

Inputs: `TASK_DIR` (the resolved task, empty for none) and `REVIEW_ROOT` (below).

Every mode persists, because `crew commit` and `crew review address` read its output.
`prepare` (crew-reviewer Step 2) chooses the directory, so a sandbox that denies the task path falls
back to a temp path instead of failing; a PR review always uses the temp form. Run it on its own
line, not as `VAR=$(…)`, which hides its prefix from a permission check, and use the path on its first
line as `REVIEW_ROOT` for the rest of the review. It writes `run.json` (mode, repo, task, creation
time), so a `/tmp` listing identifies a run — never pick a review directory with `ls -td | head -1`,
which takes the newest mtime rather than the run you are in. `crew-review-findings.py review-dir`
creates a directory alone, for a run with no diff to prepare.

`paths.txt` exists once `prepare` has read the diff; a missing one means the review has not reached
the diff, not a broken directory. Persist each
dispatched context package as `<persona>.in.md` and raw response as `<persona>.out.md`, where
`<persona>` is one of `adversarial`, `architecture`, `code-quality`, `product-flow`,
`prompt-quality`, `explorer`.

**Command surface — read it, do not probe it.** A failed invocation plus a `--help` round trip costs
two tool calls for an argument shape stated here. Positional, not flag: `crew-review-hunks.py` takes
the diff, `normalize` its input, `spec-context` the SPEC.md path. `coverage` gates a reviewer
`layers.json`; `check-map` parses a `reviewer-layers` reply;
`comments` writes the paste-ready bodies.

**PR mode has no task.** A PR review produces no SPEC.md transition, `crew commit` never reads its
output, and the resolver's task for the current branch is usually an unrelated feature. Report the artifacts as `<path> (outside task state)`; that is a
successful persist, not the `review not persisted` failure below. Pass the PR head SHA to `--head`,
and never read it from this checkout with a raw git call: the local checkout never contains the PR
head, because PR mode fetches nothing.
`persist` rejects a PR review directory whose owner has `SPEC.md`; no exception may overwrite a
task's `REVIEW.md`.

1. Write candidate findings to `$REVIEW_ROOT/candidates.json` as a JSON list (or `{"findings":
   [...]}`) with `{persona, label, title, kind, file, line, disposition, evidence, verified,
   validation, confidence, excerpt, comment, suggestion, reason, memory_ids, hunks}`. The
   authoritative set is `known` in `review_models.py`. `excerpt` is required on a PR-head
   `blocking`/`attention` finding; PR mode requires `comment` on every emitted finding and
   `suggestion` whenever the fix is a concrete replacement.
   `persona` uses the names above (a list when several flagged it); `kind` is required and its values
   are `KINDS` in `crew-review-findings.py`; `disposition` is `patch`,
   `decide`, `defer`, `dropped`, or `merged`; `hunks` lists the ids from `hunks.json` whose change
   causes the finding (omit it when there is no hunk index).
2. Run `~/.agent/bin/crew-review-findings.py normalize "$REVIEW_ROOT/candidates.json" --output
   "$REVIEW_ROOT/consolidation.json"`, adding `--hunks "$REVIEW_ROOT/hunks.json"` when that file
   exists and `--files <path1> <path2> …` always. The evidence checks run by default, so there is no
   flag to remember and no flag to pass. `--files` is what moves the evidence-path gate to
   this step: the same call rejects a finding whose `evidence` names an unchanged file, and
   without `--files` here that rejection arrives after every persona has run. Pass the same path set
   you will pass to `persist`. With `--hunks`, an emitted `blocking` or `attention` finding must cite
   at least one hunk, and every cited id must exist; a nit may stay unanchored. The default gates
   fail on a finding with no `kind`, on an emitted (`patch`/`decide`) `blocking` or `attention`
   finding without `verified: true` and an `evidence` location, on a `verified` finding with no
   `validation` sentence, and on more than `MAX_FINDINGS` emitted findings or more than `MAX_NITS`
   emitted nits; supply all three on each candidate. The caps and their rationale: `consolidation.md`. In PR mode
   evidence must use the PR-head form `path:line@headSHA7`, and the evidence excerpt belongs in the
   relevant persona `.in.md` or validator prompt. A finding verified at a PR head also carries `excerpt`: the lines
   actually read, stored on the record so it re-reads without the network
   ([evidence and comments](evidence-and-comments.md)). It canonicalizes persona names, assigns SHA-1
   fingerprints over `file|label|normalized title`, and merges exact duplicates. When `$REVIEW_ROOT/layers.json`
   exists, `persist` also runs the hunk coverage gate (step 3).
3. For every failed, skipped, or truncated dispatch, write `<persona>.out.md` before persistence
   with `status: failed|skipped|truncated`, the failure or coverage gap, and `finding: none`. A
   `.out.md` carrying any other word — or a placeholder summary without a complete no-findings
   verdict, complete finding, or documented explorer section with an item — is read as no output,
   and persistence refuses the whole run. Write each real response as it returns; never substitute a
   stub or a condensed digest (refused, per `reviewer-contract.md`). Keep that persona in `--personas`
   and name it under `### Reviewers` in the report. Then
   write the emitted report to `$REVIEW_ROOT/report.md`,
   and run `~/.agent/bin/crew-review-findings.py persist --review-dir "$REVIEW_ROOT" --report
   "$REVIEW_ROOT/report.md" --findings "$REVIEW_ROOT/consolidation.json" --mode
   <self|changes|pr|spec|idea> --files <path1> <path2> ... --head <HEAD SHA> --personas
   adversarial code-quality`; pass every dispatched persona as its own space-delimited argument (for
   example, add `architecture prompt-quality`). Comma-separated values such as
   `adversarial,code-quality` are invalid. `<HEAD SHA>` is `$(~/.agent/bin/crew-repo-info.py --field head)` for self, changes,
   spec, and idea; for PR it is the `head` SHA `$REVIEW_ROOT/head/index.json` records (files under
   `head/files/`), which the local checkout does not contain and `--head` therefore records without
   resolving.
   `--personas` is required on every call, and persona coverage is checked on every call: each
   named persona must have a real `.in.md` and `.out.md`, and the run fails when
   every persona produced nothing or when any artifact is empty, a placeholder, or a condensed
   digest. The evidence gates also run on every call — a finding with no `kind`, an unverified
   `blocking`/`attention` finding, a `verified` finding with no `validation`, and evidence outside
   `--files` all fail without a flag — plus the diff gates: hunk coverage below, and evidence paths
   checked against `--files`. `--files` takes `nargs="*"`: pass every reviewed path as its own shell
   argument, because quoting them as one string makes the evidence check treat that string as one
   nonexistent path. `--head` records the approved commit so `crew commit` and `mark-done` can
   detect a tree that moved. `--lenient` is the single supported way to skip the gates, and this
   pipeline never passes it.
   With `layers.json` in `$REVIEW_ROOT`, persistence also requires every hunk id in `hunks.json` to
   sit in exactly one layer (the check `crew-review-findings.py coverage` runs), so a map can
   never pass `coverage` and then fail persistence. It then appends `### Coverage by layer` to the
   report: one line per layer with its hunks and the emitted findings that cite them, or `no
   findings`, so the reader sees which layers drew scrutiny. Do not write that section yourself.
   With `hunks.json` present, `persist` repeats the hunk-id check from `normalize`.
   `persist` writes `REVIEW.md` (`REVIEW.<mode>.md` for spec and idea) next to the review
   directories (task-level), and appends `defer` findings to `DEFERRED.md` and `dropped` findings to
   `DROPPED.md` in the same place, because a finding cut for the nit budget was otherwise invisible.

**PR mode also writes `comments.md`**, one paste-ready body per anchor from `comment`, with
`suggestion` fenced as a GitHub suggestion block; nothing here calls `gh`. Body shape, the re-render
command, and the excerpt and base-read rules: [evidence and comments](evidence-and-comments.md).

Write scratch JSON, scripts, and packages with the harness's edit or write tool. When the tool
rejects a path, produce and consume the file in one heredoc command.

`$REVIEW_ROOT` under `~/.agent/tasks/` fails with `Operation not permitted` in a sandboxed shell
(Cursor; Claude Code writes it directly). Run `mkdir`, `normalize`, and `persist` with the harness's
permission escalation from the start, and skip that step on a harness that does not sandbox.

On exit 2 or any persistence failure, print the error and state `review not persisted`; state it only
when no `REVIEW.md` was written.

## Pipeline integration

The verdict and its metric line: [pipeline integration](pipeline-integration.md).

## Rules

- Never skip consolidation. Even with one reviewer, output goes through the consolidation format.
- Reviewers receive pre-built context first; the per-persona fetch budget is defined once, in
  `context-tiers.md`.
- The size gate applies to both self-review and PR review modes.
- For spec review, there is no size gate — specs are always reviewed in full.
- Never pad reviews with filler.
