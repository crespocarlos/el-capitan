## Pipeline integration (self and changes review)

`crew review` (self-review) and `crew review changes` are the verification between implementation
and commit. After outputting
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
- **BLOCK** — any `[blocking]` finding present. The footer states it in every mode, plan reviews
  included.

For **self-review and changes review only** (skip for PR review and spec review): run pipeline
logging.

```bash
# If PASS or WARN:
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/crew-metric.py "$TASK_DIR" review verdict=pass
fi
# If BLOCK:
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/crew-metric.py "$TASK_DIR" review verdict=block
fi
```

The next-step handoff is emitted in Step 8 of `crew-reviewer` for all modes.
