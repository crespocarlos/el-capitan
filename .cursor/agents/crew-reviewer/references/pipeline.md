## Review artifacts

Persistence is mandatory for every mode; `crew commit` and `crew review address` read its output. Resolve `TASK_DIR` first (see Pipeline Integration below). Then, before auto-apply, set `REVIEW_ROOT="$TASK_DIR/review/$(date +%Y%m%d%H%M%S)"`. Use `/tmp/crew-review-<repo>/review/$(date +%Y%m%d%H%M%S)` only when `TASK_DIR` is empty. Persist each dispatched context package as `<persona>.in.md` and raw response as `<persona>.out.md`, where `<persona>` is one of `adversarial`, `architecture`, `code-quality`, `product-flow`, `prompt-quality`, `explorer`.

1. Write candidate findings to `$REVIEW_ROOT/candidates.json` as a JSON list (or `{"findings": [...]}`) with `{persona, label, title, file, line, disposition, reason, memory_ids}`. `persona` uses the names above (a list when several flagged it); `disposition` is `patch`, `decide`, `defer`, `dropped`, or `merged`.
2. Run `~/.agent/bin/review-findings.py normalize "$REVIEW_ROOT/candidates.json" --strict --output "$REVIEW_ROOT/consolidation.json"`. `--strict` fails on an emitted (`patch`/`decide`) `blocking` or `attention` finding without `verified: true` and an `evidence` location, and on more than 7 emitted findings; add `verified` and `evidence` to each candidate. In PR mode evidence must use the PR-head form `path:line@headSHA7`, and the evidence excerpt belongs in the relevant persona `.in.md` or validator prompt. It canonicalizes persona names, assigns SHA-1 fingerprints over `file|label|normalized title`, and merges exact duplicates.
3. For every failed, skipped, or truncated dispatch, write `<persona>.out.md` before persistence with `status: failed|skipped|truncated`, the failure or coverage gap, and `finding: none`. Keep that persona in `--personas` and name it under `### Reviewers` in the report. Then write the emitted report to `$REVIEW_ROOT/report.md`, and run `~/.agent/bin/review-findings.py persist --review-dir "$REVIEW_ROOT" --report "$REVIEW_ROOT/report.md" --findings "$REVIEW_ROOT/consolidation.json" --mode <self|changes|pr|spec|idea> --files <reviewed file paths> --strict --personas <dispatched personas>`; `--strict` fails when a dispatched persona lacks its `.in.md` or `.out.md`. It writes `REVIEW.md` (`REVIEW.<mode>.md` for spec and idea) next to the review directories (task-level), and appends `defer` findings to `DEFERRED.md` in the same place.

Creating `$REVIEW_ROOT` under `~/.agent/tasks/` fails with `Operation not permitted` in a sandboxed shell. Run the `mkdir`, `normalize`, and `persist` commands with the harness's elevated-permission mechanism from the start, not after the first failure.

On exit 2 or any persistence failure, print the error and state `review not persisted` in the output; do not skip silently. State it only when no `REVIEW.md` was written.

## Pipeline Integration (self-review mode only)

`crew review` (self-review) is the quality gate between implementation and commit. After outputting the consolidated report, log the pipeline transition and provide a commit-ready conclusion.

**Resolve TASK_DIR:**

```bash
if [ -n "${CREW_TASK_DIR+x}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
elif TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null); then
  export CREW_TASK_DIR="$TASK_DIR"
else
  TASK_DIR=""
fi
```

**Verdict and transition** (based on consolidated findings):

Determine verdict first:

- **PASS** — zero findings, or only `[nit]` / `[needs more info]`
- **WARN** — `[attention]` findings only, no `[blocking]`
- **BLOCK** — any `[blocking]` finding present. `Verdict: revisit` from reviewers always maps to BLOCK.

For **self-review and changes review only** (skip for PR review and spec review): run pipeline logging.

```bash
# If PASS or WARN:
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/log-progress.py "$TASK_DIR" "REVIEW → COMMITTING"
fi
# If BLOCK:
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/log-progress.py "$TASK_DIR" "REVIEW: blocked — critical findings"
fi
```

_(Next-step handoff is emitted in Step 8 above for all modes.)_

## Rules

- Never write original findings. Personas do the reviewing — you challenge, filter, and consolidate what they return.
- Never skip consolidation. Even with one reviewer, output goes through the consolidation format.
- Reviewers receive pre-built context first. They may do up to 8 targeted fetches to ground findings they cannot verify from the provided context — but they must not re-read files already in their package.
- The size gate applies to both self-review and PR review modes.
- For spec review, there is no size gate — specs are always reviewed in full.
- Zero findings is a valid outcome.
- Never pad reviews with filler.
