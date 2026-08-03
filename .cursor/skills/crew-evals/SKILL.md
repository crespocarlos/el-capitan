---
name: crew-evals
description: "Investigate significant-events eval results. Trigger: 'crew evals'."
---

# Evals Investigation

Investigate eval results from the `.evaluation-scores*` index. Surfaces recent runs, scores, failing examples, evaluator explanations, and agent output.

## ES connection

```
ES_URL=http://elastic:changeme@localhost:9200
```

## When invoked

The user may pass an experiment ID, a suite name, or nothing. Detect the intent:

- **`crew evals`** (no args) → show latest runs for all suites, then stop
- **`crew evals <suite>`** (e.g. `crew evals significant-events`) → show latest N experiments for that suite, scores per experiment
- **`crew evals <experiment-id>`** → drill into that experiment: scores + failing examples + evaluator explanations
- **`crew evals trace <experiment-id>`** → pull agent output (discoveries/output) for all failing examples in the experiment

---

## Step 1: Latest runs

```bash
curl -s "$ES_URL/.evaluation-scores*/_search" \
  -H "Content-Type: application/json" \
  -d '{
    "size": 0,
    "aggs": {
      "by_experiment": {
        "terms": { "field": "experiment_id", "size": 30, "order": { "latest": "desc" } },
        "aggs": {
          "latest": { "max": { "field": "@timestamp" } },
          "name": { "terms": { "field": "experiment_name", "size": 1 } }
        }
      }
    }
  }' | python3 -c "
import sys, json
d = json.load(sys.stdin)
for b in d['aggregations']['by_experiment']['buckets']:
    name = b['name']['buckets'][0]['key'] if b['name']['buckets'] else '?'
    print('%s  %s  docs=%-4d  %s' % (
        b['key'][:8],
        b['latest']['value_as_string'][:19],
        b['doc_count'],
        name[:80]
    ))
"
```

Present results as a compact table. Group by scenario type (topology-continuation, main-discovery, etc.) if obvious.

---

## Step 2: Scores for an experiment

```bash
EXP_ID="<experiment-id>"

curl -s "$ES_URL/.evaluation-scores*/_search" \
  -H "Content-Type: application/json" \
  -d "{
    \"size\": 200,
    \"query\": { \"term\": { \"experiment_id\": \"$EXP_ID\" } },
    \"_source\": [\"evaluator\", \"example.id\"]
  }" | python3 -c "
import sys, json
from collections import defaultdict
d = json.load(sys.stdin)
scores = defaultdict(list)
for hit in d['hits']['hits']:
    s = hit['_source']
    ev = s.get('evaluator', {})
    name = ev.get('name', '?')
    val = ev.get('score')
    if val is not None:
        scores[name].append(val)
for metric, vals in sorted(scores.items()):
    avg = sum(vals) / len(vals)
    if avg > 1:
        print('  %-40s %.1f' % (metric, avg))
    else:
        bar = '█' * int(avg * 20)
        print('  %-40s %.2f  %s' % (metric, avg, bar))
"
```

---

## Step 3: Failing examples with evaluator explanation

```bash
EXP_ID="<experiment-id>"

curl -s "$ES_URL/.evaluation-scores*/_search" \
  -H "Content-Type: application/json" \
  -d "{
    \"size\": 200,
    \"query\": {
      \"bool\": {
        \"must\": [
          { \"term\": { \"experiment_id\": \"$EXP_ID\" } },
          { \"range\": { \"evaluator.score\": { \"lt\": 1.0 } } }
        ],
        \"must_not\": [
          { \"terms\": { \"evaluator.name\": [\"Latency\", \"Cached Tokens\", \"Input Tokens\", \"Output Tokens\", \"Tool Calls\"] } }
        ]
      }
    },
    \"_source\": [\"evaluator\", \"example.id\"]
  }" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for hit in d['hits']['hits']:
    s = hit['_source']
    ev = s.get('evaluator', {})
    example_id = s.get('example', {}).get('id', '?')
    print('example: %s  metric: %s  score: %s' % (
        example_id,
        ev.get('name', '?'),
        ev.get('score')
    ))
    explanation = ev.get('explanation', '')
    if explanation:
        print('  explanation: %s' % explanation[:400])
    print()
"
```

---

## Step 4: Agent output for a failing example

```bash
EXP_ID="<experiment-id>"
EXAMPLE_ID="<example-id>"
METRIC="grouping_correctness"  # or whichever metric you're drilling into

curl -s "$ES_URL/.evaluation-scores*/_search" \
  -H "Content-Type: application/json" \
  -d "{
    \"size\": 1,
    \"query\": {
      \"bool\": {
        \"must\": [
          { \"term\": { \"experiment_id\": \"$EXP_ID\" } },
          { \"term\": { \"example.id\": \"$EXAMPLE_ID\" } },
          { \"term\": { \"evaluator.name\": \"$METRIC\" } }
        ]
      }
    },
    \"_source\": [\"task.output\", \"evaluator\"]
  }" > /tmp/eval_output.json

python3 << 'EOF'
import json
with open('/tmp/eval_output.json') as f:
    d = json.load(f)
hit = d['hits']['hits'][0]['_source']
ev = hit.get('evaluator', {})
print('metric: %s  score: %s' % (ev.get('name'), ev.get('score')))
print('explanation: %s' % ev.get('explanation', ''))
print()

output = hit.get('task', {}).get('output', {})
discoveries = output.get('discoveries', [])
print('discoveries: %d' % len(discoveries))
for i, disc in enumerate(discoveries):
    print('\n--- Discovery %d: %s' % (i+1, disc.get('title', '?')))
    print('  severity: %s  confidence: %s' % (disc.get('severity'), disc.get('confidence')))
    for sig in disc.get('signals', []):
        rn = sig.get('metadata', {}).get('rule_name', '?')
        conf = sig.get('confirmed', '?')
        print('  rule: %s [confirmed=%s]' % (rn, conf))
    causal = [c['feature_id'] for c in disc.get('causal_features', [])]
    print('  causal_features: %s' % causal)
    for b in disc.get('blast_radius', []):
        src = b.get('source', b.get('feature_id', '?'))
        tgt = b.get('target', b.get('name', '?'))
        print('  blast [%s]: %s -> %s' % (b.get('type', '?'), src, tgt))
EOF
```

---

## Step 5: KI store snapshot (what features are available)

```bash
curl -s "$ES_URL/.significant_events-knowledge_indicators/_search" \
  -H "Content-Type: application/json" \
  -d '{
    "size": 200,
    "_source": ["id", "type", "title", "feature.type", "feature.id", "feature.title",
                "feature.properties.source", "feature.properties.target", "feature.properties.protocol"]
  }' | python3 -c "
import sys, json
from collections import defaultdict
d = json.load(sys.stdin)
print('total KIs: %d' % d['hits']['total']['value'])
by_type = defaultdict(list)
seen = set()
for hit in d['hits']['hits']:
    s = hit['_source']
    sid = s.get('id', '?')
    if sid in seen:
        continue
    seen.add(sid)
    feat = s.get('feature', {})
    ftype = feat.get('type', s.get('type', '?'))
    stitle = feat.get('title', '') or s.get('title', '?')
    props = feat.get('properties', {})
    src, tgt = props.get('source', ''), props.get('target', '')
    by_type[ftype].append((sid, stitle, src, tgt, props.get('protocol', '')))

for t, items in sorted(by_type.items()):
    print()
    print('=== %s ===' % t)
    for sid, title, src, tgt, proto in items:
        if src or tgt:
            print('  %s: %s -> %s (%s)' % (sid[:20], src, tgt, proto))
        else:
            print('  %s: %s' % (sid[:20], title))
"
```

---

## Output format

After running the relevant steps, present findings in this order:

1. **Scores table** — all metrics for the experiment, with pass/fail visual
2. **Failing examples** — one block per example, metric + score + evaluator explanation
3. **Root cause analysis** — for each failing example: what the agent produced (discoveries, causal_features, blast_radius) vs. what was expected
4. **KI gap** — if causal_features or blast_radius look wrong, check the KI store (Step 5) to determine whether the data exists at all

Concise diagnosis at the end: is this an instruction issue (agent reasoning incorrectly about available data) or a data gap (KI graph missing the topology needed to group correctly)?
