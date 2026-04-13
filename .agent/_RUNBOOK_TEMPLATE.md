# [Change Title] — Validation Runbook

> This runbook validates the implementation end-to-end. It is a local agent artifact — not committed to the repo.
> Run each section in order. Sections with a **Pass:** criterion are auto-executable by `crew test`.
> Sections marked `type: visual` or `type: judgment` require human verification.

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

## 3. [type: playwright — Section Title]

[One sentence: what DOM assertion this section verifies.]

- **Navigate:** $SERVICE_URL/app/path
- **Auth:** (optional) bearer $API_KEY
- **Wait:** (optional) [selector to wait for before asserting]
- **Assert:** [data-test-subj="element"]
- **Pass:** element is visible on the page
- **Fail:** selector not found — check that the element renders under the given auth/route

---

## 4. [type: visual — Section Title]

[What to look at in the UI or system output. No executable block — requires human eyes.]

**Pass:** [what "looks correct" means concretely]

---

## Common Failures and Fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| [observable symptom] | [root cause] | [remediation step] |
| [observable symptom] | [root cause] | [remediation step] |
