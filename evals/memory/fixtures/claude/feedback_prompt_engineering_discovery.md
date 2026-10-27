---
name: feedback-prompt-engineering-discovery
description: "Best practices and anti-patterns learned from discovery agent eval failures and prompt fixes, specific to the significant_events/discovery agent"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c29b06e4-044a-427e-a5ad-9228cdb5f820
  modified: 2026-08-21T10:53:25.766Z
---

Do not add prose-only restatements of existing rules — add structural constraints instead.

**Why:** Discovery eval failures were caused by the model following rules in spirit but missing the binding step. Prose like "do not copy signals" doesn't prevent copying; an explicit ownership-map pattern ("construct rule_uuid→signal map, one entry per rule, before composing any item") forces the right structure. Same for event_id: "record rule_uuid→accepted_event_id immediately on acceptance" + "confirm in pre-write check" gives two structural enforcement points.

**How to apply:** When a failure mode is "model forgets to do X at emit time," fix it at THREE layers: (1) bind the value at decision time (Step 4), (2) carry it through an explicit map, (3) enforce with a pre-write check that says "if it fails, rebuild from the map." Prose rules alone at the emit step always lose to context pressure.

---

Dispatch simultaneous tool calls before interpreting results to prevent skipped searches.

**Why:** Topology continuation failures (cycle 2 skipping topology search) happened because the model completed a Rule Match, saw it partially handled routing, and skipped the topology search. The fix: "When topology_feature_ids is non-empty, dispatch Rule Match and Topology Match in the same tool-call group. Do not interpret either result until both return." This makes the two-search pattern atomic.

**How to apply:** Whenever there are two searches that must both run regardless of the first's result, instruct the model to dispatch them simultaneously and explicitly forbid interpretation until both return. Use "same tool-call group" (consistent with existing "tool batch" terminology in the prompts).

---

Move mandatory context-gathering steps BEFORE the main procedure, not mid-procedure.

**Why:** In the original prompt, the memory check was buried in Step 1 item 4, after KI grounding. The model would sometimes skip it or run it after routing decisions were already being formed. Moving memory to its own Step 1 (with explicit sequencing: memory → classify → THEN load KI grounding) gives it the right weight.

**How to apply:** For any step that conditions ALL subsequent decisions (memory classification, context retrieval), make it the first step with its own heading. Don't embed it inside the main processing step.

---

Use `flaky_probe` flag pattern instead of raw count thresholds to control status suppression.

**Why:** Using `recent_detection_count` directly caused real incidents to be suppressed when rules happened to fire often. The workflow-side `flaky_probe: true` flag means: the workflow already made the high-count determination and delayed this detection deliberately. The agent should only apply chronic/noise logic when `flaky_probe: true`.

**How to apply:** Never use raw metric thresholds in prompt logic. Use explicit workflow-set flags. Raw counts in agent prompts create invisible suppression paths that are hard to debug in traces.

---

Topology Match acceptance: "sufficient acceptance evidence" beats "<incident_matching>"

**Why:** The old prompt required Topology Match to pass `<incident_matching>` (a multi-step evaluation). The model would find topology overlap, decide the evidence didn't fully match the narrative, and reject → emit without `event_id`. Fix: "grounded causal_features[].feature_id or blast_radius[].feature_id appears in stored topology → sufficient acceptance evidence." Simpler criterion, unambiguous, directly grounded.

**How to apply:** When simplifying acceptance criteria in prompt routing, pair it with a concrete rejection criterion ("reject only when Current evidence identifies a distinct resource or dependency path ABSENT from stored topology") so the simplification has a clear boundary.

---

Fixed-point topology closure before composing items prevents cascade merge duplicates.

**Why:** The model was copying bridge signals during cascade merges because it stopped merging after one pass. Fix: "Repeatedly merge any two groups whose topology sets share a causal_features or blast_radius node, until no merge remains." The "until no merge remains" is the critical phrase — without it, transitive merges are missed.

**How to apply:** Any grouping/merge operation that might be transitive needs an explicit "until stable" termination condition in the instruction. Add a violation consequence: "emitting separate items that still share one of these nodes is invalid."
