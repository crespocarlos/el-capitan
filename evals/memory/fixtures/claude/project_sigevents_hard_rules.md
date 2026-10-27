---
name: sigevents-hard-rules
description: Two hard constraints on the Significant Events detection/discovery architecture doc — Alerting v2 and Investigations are consumed exactly as they exist on main; no asks to either team
metadata: 
  node_type: memory
  type: project
  originSessionId: 0211c1ed-04ca-4e67-bae6-6acdec5573f6
  modified: 2026-09-23T15:02:46.810Z
---

Hard rules for `significant_events/.../discovery/discovery_architecture_analysis.md` (set 2026-09-23):

1. **No changes to Alerting v2.** Use rules-as-data (`standalone` queries, `grouping.fields`, `kind`), `state_transition`, `no_data_strategy`, action policies (`destinations: workflow` only; `matcher`, `groupBy`, `throttle`; **no delay**), `.alert-actions`, the director FSM — as on `main`. Nothing of ours writes `.rule-events`.
2. **No changes to Investigations.** Consume as-is: Automations start investigations from alerts v2 sources; conclusions read from their store as stored; Cortex pages (`nightshift_investigations/common/cortex.ts`, markdown `content`) read-only as prose; `cortex_optimize` only reads investigation transcripts — no external input. Investigations emits no action/write-back for us (no `deactivate` with `actor: investigation`).

**Why:** user: "let's not propose new changes to alerts v2. we must use what alerts v2 provides, that's a hard rule" and "another hard rule. same as alerts v2, investigation remains as is. we don't touch it as part of this, we consume it as is."

**How to apply:** before adding any edge/field that another team would have to build, check it exists on `main`; if not, either drop it or reframe as consumption of an existing store. Mark anything of ours **(proposed)**. Related: [[challenge-dont-accept]].
