## Pipeline integration (self and changes review)

`crew review` (self-review) and `crew review changes` are the verification between implementation
and commit. After outputting
the consolidated report, log the pipeline transition and provide a commit-ready conclusion.

**Resolve TASK_DIR:**

```bash
TASK_DIR=$(~/.agent/bin/crew-tool.py task-context --field task_dir)   # honors CREW_TASK_DIR
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
VERDICT=pass   # block for BLOCK
[ -z "$TASK_DIR" ] || ~/.agent/bin/crew-tool.py task-log "$TASK_DIR" --metric review verdict=$VERDICT
```

The next-step handoff is emitted in Step 8 of `crew-reviewer` for all modes.
