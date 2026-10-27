## Review artifacts

Before auto-apply, set `REVIEW_ROOT="$TASK_DIR/review/$(date +%Y%m%d%H%M%S)"`; when no task exists, use `/tmp/crew-review-<repo>/review/$(date +%Y%m%d%H%M%S)`. Persist each dispatched context package as `<persona>.in.md` and raw response as `<persona>.out.md`.

Write `consolidation.json` as a list of `{fingerprint, persona, label, title, file, disposition, reason, memory_ids}`. The fingerprint is SHA-1 of `file|label-category|normalized title`; disposition is `kept`, `dropped`, or `merged`.

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
~/.agent/bin/log-progress.py "$TASK_DIR" "REVIEW → COMMITTING"
# If BLOCK:
~/.agent/bin/log-progress.py "$TASK_DIR" "REVIEW: blocked — critical findings"
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
