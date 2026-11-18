## Review artifacts

Persistence is mandatory for every mode; `crew commit` and `crew review address` read its output.
Set `REVIEW_ROOT` before auto-apply. For self, changes, spec, and idea reviews, resolve `TASK_DIR`
first (see Pipeline Integration below) and use `REVIEW_ROOT="$TASK_DIR/review/$(date
+%Y%m%d%H%M%S)"`; use `/tmp/crew-review-<repo>/review/$(date +%Y%m%d%H%M%S)` when `TASK_DIR` is
empty. For PR review, do not resolve `TASK_DIR` at all — always use the `/tmp` form. Persist each
dispatched context package as `<persona>.in.md` and raw response as `<persona>.out.md`, where
`<persona>` is one of `adversarial`, `architecture`, `code-quality`, `product-flow`,
`prompt-quality`, `explorer`.

**Command surface — read it, do not probe it.** A failed invocation plus a `--help` round trip costs
two tool calls to learn an argument shape this section already states. Two entry points are easy to
confuse: `review-hunks.py` takes the diff as a **positional** argument (there is no `--diff` flag),
and `review-findings.py normalize` takes its input positionally (there is no `--input` flag).
`coverage` is the gate for a reviewer `layers.json`; `validate-map` belongs to `crew explain` and
rejects a `layers.json` for lacking `--review`. Every remaining argument shape is specified in the
numbered steps below, next to the invocation that uses it.

**PR mode has no task.** A PR review produces no SPEC.md transition, `crew commit` never reads its
output, and `resolve-task-dir.py` answers with the newest non-DONE task for the current branch —
usually an unrelated feature. Report the artifacts as `<path> (outside task state)`; that is a
successful persist, not the `review not persisted` failure below. Pass the PR head SHA to `--head`,
never `git rev-parse HEAD`; the local checkout never contains the PR head (PR mode fetches nothing).
`persist` rejects a PR review directory whose owner has `SPEC.md`; no exception may overwrite a
task's `REVIEW.md`.

1. Write candidate findings to `$REVIEW_ROOT/candidates.json` as a JSON list (or `{"findings":
   [...]}`) with `{persona, label, title, file, line, disposition, reason, memory_ids, hunks}`.
   `persona` uses the names above (a list when several flagged it); `disposition` is `patch`,
   `decide`, `defer`, `dropped`, or `merged`; `hunks` lists the ids from `hunks.json` whose change
   causes the finding (omit it when there is no hunk index).
2. Run `~/.agent/bin/review-findings.py normalize "$REVIEW_ROOT/candidates.json" --strict --output
   "$REVIEW_ROOT/consolidation.json"`, adding `--hunks "$REVIEW_ROOT/hunks.json"` when that file
   exists. With `--hunks`, an emitted `blocking` or `attention` finding must cite at least one hunk,
   and every cited id must exist; a nit may stay unanchored. `--strict` fails on an emitted (`patch`/`decide`) `blocking`
   or `attention` finding without `verified: true` and an `evidence` location, and on more than
   `MAX_FINDINGS` emitted findings or more than `MAX_NITS` emitted nits; add `verified` and
   `evidence` to each candidate. The two caps are defined once, in `review-findings.py`, and
   restated with their rationale in `consolidation.md` — read them there rather than copying the
   numbers, so a cap change cannot leave this file stale. In PR mode evidence must use
   the PR-head form `path:line@headSHA7`, and the evidence excerpt belongs in the relevant persona
   `.in.md` or validator prompt. It canonicalizes persona names, assigns SHA-1 fingerprints over
   `file|label|normalized title`, and merges exact duplicates. When `$REVIEW_ROOT/layers.json`
   exists, `persist --strict` also runs the hunk coverage gate (step 3).
3. For every failed, skipped, or truncated dispatch, write `<persona>.out.md` before persistence
   with `status: failed|skipped|truncated`, the failure or coverage gap, and `finding: none`. A
   `.out.md` carrying any other word — or a placeholder summary without a complete no-findings
   verdict, complete finding, or documented explorer section with an item — is read as no output,
   and `--strict` refuses the whole run. Write each real response as it returns; never substitute a
   stub. Keep that persona in `--personas` and name it under `### Reviewers` in the report. Then
   write the emitted report to `$REVIEW_ROOT/report.md`,
   and run `~/.agent/bin/review-findings.py persist --review-dir "$REVIEW_ROOT" --report
   "$REVIEW_ROOT/report.md" --findings "$REVIEW_ROOT/consolidation.json" --mode
   <self|changes|pr|spec|idea> --files <path1> <path2> ... --head <HEAD SHA> --strict --personas
   adversarial code-quality`; pass every dispatched persona as its own space-delimited argument (for
   example, add `architecture prompt-quality`). Comma-separated values such as
   `adversarial,code-quality` are invalid. `<HEAD SHA>` is `$(git rev-parse HEAD)` for self, changes,
   spec, and idea; for PR it is the head SHA from `gh pr view`, which the local checkout does not
   contain and `--head` therefore records without resolving.
   `--strict` fails when a dispatched persona lacks its `.in.md` or `.out.md`, when every persona
   is failed or skipped, or when a finding's evidence cites a file outside `--files`. `--files` takes
   `nargs="*"`: pass every reviewed path as its own shell argument — quoting them all as one string
   makes strict persistence treat that string as one nonexistent path and reject otherwise valid
   evidence. `--head`
   records the approved commit so `crew commit` and `--mark-done` can detect a tree that moved.
   With `layers.json` in `$REVIEW_ROOT`, `--strict` also requires every hunk id in `hunks.json` to
   sit in exactly one layer (`review-findings.py coverage`, shared with `validate-map`), so a map can
   never pass validation and then fail coverage. It then appends `### Coverage by layer` to the
   report: one line per layer with its hunks and the emitted findings that cite them, or `no
   findings`, so the reader sees which layers drew scrutiny. Do not write that section yourself.
   With `hunks.json` present, `--strict` repeats the hunk-id check from `normalize`.
   `--strict` writes `REVIEW.md` (`REVIEW.<mode>.md` for spec and idea) next to the review
   directories (task-level), and appends `defer` findings to `DEFERRED.md` in the same place.

Write scratch JSON, scripts, and assembled context packages with the harness's edit or write tool at a
path that tool permits. Measure the permitted set, do not assume it: the Cursor `Write` tool refuses
`/tmp` and other paths outside the workspace worktrees, but accepts the task directory under
`~/.agent/tasks/` and `~/.agent/` generally. `check-write-boundary.sh` allows `$HOME/.agent/`,
`$HOME/.claude/`, `$HOME/.cursor/`, and `/tmp` — a superset of what the tool allows, so the tool is
the binding constraint and a `/tmp` path fails before the hook is consulted.

When a scratch file has no permitted home, produce it and consume it in one shell command with a
heredoc (`python3 - <<'PY' … PY`). A heredoc is the fallback for content that never needs to persist,
not the default for writing files.

Creating `$REVIEW_ROOT` under `~/.agent/tasks/` fails with `Operation not permitted` in a sandboxed
shell (Cursor; Claude Code writes it directly). Run the `mkdir`, `normalize`, and `persist` commands
with the harness's permission escalation from the start, not after the first failure, and skip that
step on a harness that does not sandbox the shell.

On exit 2 or any persistence failure, print the error and state `review not persisted` in the
output; do not skip silently. State it only when no `REVIEW.md` was written.

## Pipeline Integration (self-review mode only)

`crew review` (self-review) is the quality gate between implementation and commit. After outputting
the consolidated report, log the pipeline transition and provide a commit-ready conclusion.

**Resolve TASK_DIR:**

```bash
if [ -n "${CREW_TASK_DIR:-}" ]; then
  TASK_DIR="$CREW_TASK_DIR"; CREW_TASK_STATE=ok
elif [ -n "${CREW_TASK_STATE:-}" ]; then
  TASK_DIR=""   # already resolved this session; task-env.sh owns the tri-state
else
  source ~/.agent/bin/task-env.sh
fi
```

**Verdict and transition** (based on consolidated findings):

Determine verdict first:

- **PASS** — zero findings, or only `[nit]` / `[needs more info]`
- **WARN** — `[attention]` or `[concern]` findings only, no `[blocking]`
- **BLOCK** — any `[blocking]` finding present. `Verdict: revisit` from reviewers always maps to
  BLOCK.

For **self-review and changes review only** (skip for PR review and spec review): run pipeline
logging.

```bash
# If PASS or WARN:
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/log-metric.py "$TASK_DIR" review verdict=pass
fi
# If BLOCK:
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/log-metric.py "$TASK_DIR" review verdict=block
fi
```

_(Next-step handoff is emitted in Step 8 above for all modes.)_

## Rules

- Never write original findings. Personas do the reviewing — you challenge, filter, and consolidate
  what they return.
- Never skip consolidation. Even with one reviewer, output goes through the consolidation format.
- Reviewers receive pre-built context first; the per-persona fetch budget is defined once, in
  `context-tiers.md`.
- The size gate applies to both self-review and PR review modes.
- For spec review, there is no size gate — specs are always reviewed in full.
- Never pad reviews with filler.
