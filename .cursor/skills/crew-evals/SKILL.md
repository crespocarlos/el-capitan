---
name: crew-evals
description: "Inspect and compare evaluation experiments. Trigger: 'crew evals', or after an eval run when scores need explaining or comparing."
---
# Evals

Two tools, both read-only and stdlib-only. Elasticsearch configuration uses `ES_URL`, plus `ES_API_KEY` or `ES_USER` and `ES_PASS`; exit 2 means the service is unavailable.

## Inspect one experiment: `~/.agent/bin/evals-inspect.py`
- no argument: `latest`
- experiment: `scores <exp>` then `failures <exp>`
- `trace <exp> <example>`: `trace <exp> <example>`
- `ki`, `flips <a> <b>`, and `cluster <exp>...` map directly.

## Compare runs: `~/.agent/bin/evals-compare.py`
Groups runs by commit sha; use it to answer "did this change help?".
- `runs`: list runs (commit groups), newest first.
- `compare [COMMIT ...] [--exp TEXT] [--all]`: one table per experiment, one column per commit; the first commit is the baseline (default: last 3 commits).
- `detail COMMIT [--below 1] [--ev TEXT] [--chars N]`: scores under a threshold with the judge's explanation.
- `traces COMMIT`: per trace tools, query targets, and prefetched context.

Rules:
- Report a score change only against a named baseline commit; run `compare` before claiming improvement.
- For a regression, run `detail` on the failing commit first, then `traces` for the failing example; debug from the trace, not from the score.
- `QUALITY_FIRST` evaluator names and experiment labels are sigevents defaults; other evaluators appear in `compare` only with `--all`.
- In Kibana, `node scripts/evals compare` is an alternative for run-to-run diffs.
