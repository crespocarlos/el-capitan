---
disable-model-invocation: true
name: crew-evals
description: "Inspect evaluation experiments. Trigger: 'crew evals'."
---
# Evals

Route commands to `~/.agent/bin/evals-inspect.py`:
- no argument: `latest`
- experiment: `scores <exp>` then `failures <exp>`
- `trace <exp> <example>`: `trace <exp> <example>`
- `ki`, `flips <a> <b>`, and `cluster <exp>...` map directly.

Use `node scripts/evals compare` in Kibana for run-to-run evaluation diffs. Elasticsearch configuration uses `ES_URL`, plus `ES_API_KEY` or `ES_USER` and `ES_PASS`; exit 2 means the service is unavailable.
