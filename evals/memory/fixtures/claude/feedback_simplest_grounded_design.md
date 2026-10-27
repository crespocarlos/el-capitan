---
name: simplest-grounded-design
description: Design by iterative rounds validated on live data; reject new files/APIs/concepts unless the data proves them necessary
metadata:
  node_type: memory
  type: feedback
  originSessionId: d945c3a2-82ef-4c6b-bf78-ec3102a3a450
  modified: 2026-10-23T09:38:04.632Z
---

When designing (e.g. the SigEvents classifier), start from the simplest thing that reuses existing code and data, then
iterate in rounds: design → validate against live cluster data → reflect → simplify. Weigh every decision by what it
improves and what it does not. Ask instead of guessing.

**Why:** On 2026-10-23 I proposed a classifier spec with a new data source, an external API (execution history), new
files and ~8 untuned constants; the user called it overengineered twice and asked "what does this endpoint do that
the current classifier can't?" — it added almost nothing. Existing code (`observeMatchSeries` already fetches 60
buckets) covered the need.

**How to apply:** before proposing a new file, client, API or concept, show (with data or code) what the existing
pieces cannot do. Prefer extending existing modules (`RuleEventsClient`, `baseline.ts`) over new ones. Related:
[[challenge-dont-accept]], [[sigevents-hard-rules]].
