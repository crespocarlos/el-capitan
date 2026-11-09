## Review artifacts

Persistence is mandatory for every mode; `crew commit` and `crew review address` read its output.
Set `REVIEW_ROOT` before auto-apply. For self, changes, spec, and idea reviews, resolve `TASK_DIR`
first (see Pipeline Integration below) and use `REVIEW_ROOT="$TASK_DIR/review/$(date
+%Y%m%d%H%M%S)"`; use `/tmp/crew-review-<repo>/review/$(date +%Y%m%d%H%M%S)` when `TASK_DIR` is
empty. For PR review, do not resolve `TASK_DIR` at all — always use the `/tmp` form. Persist each
dispatched context package as `<persona>.in.md` and raw response as `<persona>.out.md`, where
`<persona>` is one of `adversarial`, `architecture`, `code-quality`, `product-flow`,
`prompt-quality`, `explorer`.

**PR mode has no task.** A PR review produces no SPEC.md transition, `crew commit` never reads its
output, and `resolve-task-dir.py` answers with the newest non-DONE task for the current branch —
usually an unrelated feature. Report the artifacts as `<path> (outside task state)`; that is a
successful persist, not the `review not persisted` failure below. Pass the PR head SHA to `--head`,
never `git rev-parse HEAD`; the local checkout never contains the PR head (PR mode fetches nothing).
`persist` rejects a PR review directory whose owner has `SPEC.md`; no exception may overwrite a
task's `REVIEW.md`.

1. Write candidate findings to `$REVIEW_ROOT/candidates.json` as a JSON list (or `{"findings":
   [...]}`) with `{persona, label, title, file, line, disposition, reason, memory_ids}`. `persona`
   uses the names above (a list when several flagged it); `disposition` is `patch`, `decide`,
   `defer`, `dropped`, or `merged`.
2. Run `~/.agent/bin/review-findings.py normalize "$REVIEW_ROOT/candidates.json" --strict --output
   "$REVIEW_ROOT/consolidation.json"`. `--strict` fails on an emitted (`patch`/`decide`) `blocking`
   or `attention` finding without `verified: true` and an `evidence` location, and on more than 7
   emitted findings; add `verified` and `evidence` to each candidate. In PR mode evidence must use
   the PR-head form `path:line@headSHA7`, and the evidence excerpt belongs in the relevant persona
   `.in.md` or validator prompt. It canonicalizes persona names, assigns SHA-1 fingerprints over
   `file|label|normalized title`, and merges exact duplicates.
3. For every failed, skipped, or truncated dispatch, write `<persona>.out.md` before persistence
   with `status: failed|skipped|truncated`, the failure or coverage gap, and `finding: none`. A
   `.out.md` carrying any other word — or a placeholder summary without a complete no-findings
   verdict, complete finding, or documented explorer section with an item — is read as no output,
   and `--strict` refuses the whole run. Write each real response as it returns; never substitute a
   stub. Keep that persona in `--personas` and name it under `### Reviewers` in the report. Then
   write the emitted report to `$REVIEW_ROOT/report.md`,
   and run `~/.agent/bin/review-findings.py persist --review-dir "$REVIEW_ROOT" --report
   "$REVIEW_ROOT/report.md" --findings "$REVIEW_ROOT/consolidation.json" --mode
   <self|changes|pr|spec|idea> --files <reviewed file paths> --head <HEAD SHA> --strict --personas
   adversarial code-quality`; pass every dispatched persona as its own space-delimited argument (for
   example, add `architecture prompt-quality`). Comma-separated values such as
   `adversarial,code-quality` are invalid. `<HEAD SHA>` is `$(git rev-parse HEAD)` for self, changes,
   spec, and idea; for PR it is the head SHA from `gh pr view`, which the local checkout does not
   contain and `--head` therefore records without resolving.
   `--strict` fails when a dispatched persona lacks its `.in.md` or `.out.md`, when every persona
   is failed or skipped, or when a finding's evidence cites a file outside `--files`. `--head`
   records the approved commit so `crew commit` and `--mark-done` can detect a tree that moved.
   `--strict` writes `REVIEW.md` (`REVIEW.<mode>.md` for spec and idea) next to the review
   directories (task-level), and appends `defer` findings to `DEFERRED.md` in the same place.

Build scratch JSON, scripts, and assembled context packages with a shell heredoc
(`python3 - <<'PY' … PY`). Do not rely on the file-write tool for a path outside the workspace: the
Cursor `Write` tool refuses paths outside the workspace worktrees, including `/tmp`, while Claude
Code writes what the sandbox allows. A heredoc works in both.

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
  ~/.agent/bin/log-progress.py "$TASK_DIR" "review: passed"
fi
# If BLOCK:
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/log-progress.py "$TASK_DIR" "REVIEW: blocked — critical findings"
fi
```

_(Next-step handoff is emitted in Step 8 above for all modes.)_

## Rules

- Never write original findings. Personas do the reviewing — you challenge, filter, and consolidate
  what they return.
- Never skip consolidation. Even with one reviewer, output goes through the consolidation format.
- Reviewers receive pre-built context first. They may do up to 8 targeted fetches to ground findings
  they cannot verify from the provided context — but they must not re-read files already in their
  package.
- The size gate applies to both self-review and PR review modes.
- For spec review, there is no size gate — specs are always reviewed in full.
- Zero findings is a valid outcome.
- Never pad reviews with filler.
