---
name: crew-address-review
description: "Work through findings from the most recent crew review inline. Trigger: 'crew review address'."
---

**Workflow**: build | **Stage**: post-review

# Address Review

## When Invoked

### Step 1: Locate findings

Check if a `## Review:` heading is visible in the current session conversation. If yes, use those findings directly — do not read any file.

If no review is visible in context (new session or context reset):

```bash
TASK_DIR=$(python3 ~/.agent/bin/resolve-task-dir.py 2>/dev/null)
REPO=$(basename $(git rev-parse --show-toplevel))
OUTPUT_DIR=${TASK_DIR:-/tmp/crew-review-$REPO}
REVIEW_FILE="$OUTPUT_DIR/REVIEW.md"
```

If `$REVIEW_FILE` exists, read it. If neither source is available, stop:

> "No review found. Run `crew review` first, then `crew review address`."

### Step 2: Triage findings

Parse the findings list. Categorize:

- **Must address**: all `[blocking]` findings
- **Should address**: all `[suggestion]` and `[concern]` findings
- **Optional**: `[question]` and `[nit]` findings

Print a triage summary before starting:

```
Findings to address:
  [blocking]   N  — must fix
  [suggestion] N  — should fix
  [question]   N  — needs answer
  [nit]        N  — optional

Starting with [blocking] findings.
```

### Step 3: Work through findings in priority order

For each finding, starting with `[blocking]`:

1. State the finding title and label
2. Explain what you'll change and why
3. Make the edit (read the relevant file first if needed)
4. Confirm the change in one sentence

Work through `[blocking]` findings first, then `[suggestion]`/`[concern]`, then ask the user whether to continue to `[question]` and `[nit]` items:

> "Blocking and suggestion findings addressed. Continue with questions and nits? (Y/n)"

### Step 4: Summary

After all selected findings are addressed, print:

```
Review addressed:
  ✓ [blocking]   N fixed
  ✓ [suggestion] N fixed
  — [question]   N (skipped / answered inline)
  — [nit]        N (skipped)

Run `crew review` to verify, or `crew commit` if satisfied.
```
