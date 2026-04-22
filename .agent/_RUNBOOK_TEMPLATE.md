# [Change Title] — Validation Runbook

> This runbook is a **local agent artifact** — not committed to the repo.
> **Scriptable only:** each numbered section must include a **fenced** shell or Python command and an explicit **`Pass:`** line so `crew test` can auto-run it.
> **Do not** use this file for long manual QA matrices, human judgment, or UI "does it look right" checks — those belong in **Acceptance Criteria** / task **Acceptance** in SPEC.md.
> Oversized command logs belong in `$TASK_DIR/artifacts/` with a short excerpt in REPORT.md (see `crew-builder` Completion Protocol).

## Prerequisites

```bash
# Set environment variables needed across all sections
export SERVICE_URL=http://localhost:<port>
export USERNAME=<user>
export PASSWORD=<password>
# Add API keys or other config as needed
```

Resolve any dynamic IDs or config values before running the sections below:

```bash
# Example: resolve a workflow or resource ID dynamically
RESOURCE_ID=$(curl -s -u "$USERNAME:$PASSWORD" "$SERVICE_URL/api/resources" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['results'][0]['id'])")
echo "RESOURCE_ID=$RESOURCE_ID"
```

---

## 1. [Section Title]

[One sentence: what this section verifies and why it matters.]

```bash
<executable bash or Python command with deterministic output>
```

**Pass:** [explicit criterion — output value, HTTP status, count threshold, field value]
**Fail:** [what failure means and where to look next]

---

## 2. [Section Title]

[One sentence: what this section verifies.]

```bash
<executable command>
```

**Pass:** [explicit criterion]
**Fail:** [diagnosis hint]

---

## Common Failures and Fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| [observable symptom] | [root cause] | [remediation step] |
| [observable symptom] | [root cause] | [remediation step] |
