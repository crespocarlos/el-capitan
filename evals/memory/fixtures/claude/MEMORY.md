# Memory Index

- [Discovery Agent Prompt Engineering Best Practices](feedback_prompt_engineering_discovery.md) — Structural patterns and anti-patterns for discovery prompt changes, learned from eval failure analysis
- [Challenge, don't accept](feedback_challenge_dont_accept.md) — push back on findings and prompts; "too complicated" = strip plumbing, keep blocks; record trade-offs in Decisions
- [SigEvents hard rules](project_sigevents_hard_rules.md) — Alerting v2 and Investigations consumed exactly as on main; no asks to either team; Cortex is markdown, optimizer reads transcripts only
- [SigEvents lifecycle decisions](project_sigevents_lifecycle_decisions.md) — single status writer, no agent-gated closure, doc + review locations, open R1-R3
- [SigEvents #1502/#1081 c0 findings](project_sigevents_1502_1081_c0_findings.md) — c0 cost split, skip back-test, continuity numbers; start with the #1502 cost half
- [Eval compare script](reference_eval_compare_script.md) — one command to compare sigevents eval runs and verify the arm from traces
- [Simplest grounded design](feedback_simplest_grounded_design.md) — iterate in rounds validated on live data; no new files/APIs unless data proves need
- [SigEvents classifier c0 replay](project_sigevents_classifier_c0_replay.md) — 88% of c0 detections are agent no-ops; never filter non-members; review memory safe for members; stamps not worth it
- [SigEvents c0 context compaction](project_sigevents_c0_context_compaction.md) — measured root cause of c0 discovery restarts, compaction mechanics, batching lever, user decisions (no compaction prep, LIMIT 5, no attachment)
- [c0 access how-to](reference_c0_access_howto.md) — read-only c0 traces, conversations, workflows and ES|QL via console proxy
- [SigEvents c0 smart sampling rounds](project_sigevents_c0_smart_sampling_rounds.md) — 3-round c0 exploration of query-level sample trimming (keep LIMIT 5), learnings per round
- [No repair steps in prompts](feedback_prompt_no_repair_steps.md) — fix root cause (one owner per decision), never add a late rule that patches an earlier step
