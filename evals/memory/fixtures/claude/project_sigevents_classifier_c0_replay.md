---
name: sigevents-classifier-c0-replay
description: "c0 replay (2026-10-23) of detection-classifier designs — what the waste is, what filters it safely, what must never be filtered"
metadata:
  node_type: memory
  type: project
  originSessionId: d945c3a2-82ef-4c6b-bf78-ec3102a3a450
  modified: 2026-10-23T09:50:37.885Z
---

Replayed 643 c0 detections (3 days, 95 rules, classifier not deployed there) against designs, labelled by what the
agent did (verdict written for the rule within 40 min). 567 (88%) led to nothing; 71 useful (57 rule added to an
event, 14 verdict changed).

Findings:
- `.rule-events` signal buckets equal the rule's KI query on logs bucket-for-bucket (after rule creation) — no new data
  source needed; `observeMatchSeries` already sees what the detector sees.
- c0 noise is not on/off flapping (51 of 95 rules are mostly-off sparse, 13 chronic); v1/v2 persistence+flap saved 8/567.
- 247 wasted calls are rules in no live event; filtering them ("already reviewed") delays onsets ~25h median (next
  detection is a day later) or loses them — never filter `not_live_member`.
- Review memory (last agent-processed detection, valid 4h, own series unchanged) as the reference for members: 250/567
  skipped, 1 miss (a relevance re-judgment with flat data). Judged-level stamps on the write path add only 3/567 —
  not worth the write-path complexity.
- The 24h flaky gate holds only waste on c0 (72, 0 useful, none with change reasons).

**Why:** grounds every classifier decision in measured recall/cost instead of reasoning.
**How to apply:** rerun the replay (scratchpad scripts `replay_lib.py`, `r3.py`) before changing classifier rules;
recall on `added`/`changed` is the bar. Related: [[simplest-grounded-design]], [[sigevents-lifecycle-decisions]].
