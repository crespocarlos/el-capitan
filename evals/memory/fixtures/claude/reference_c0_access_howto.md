---
name: c0-access-howto
description: "Read-only ways to inspect c0 agent traces, conversations, workflows and run ES|QL on source views via the console proxy"
metadata:
  node_type: memory
  type: reference
  originSessionId: d945c3a2-82ef-4c6b-bf78-ec3102a3a450
  modified: 2026-10-26T16:40:12.927Z
---

All read-only through `~/Documents/dev/nightshift-c0-debug/c0-kibana.sh` (never print secrets or customer values; aggregates and field names only).

- Agent traces: data stream `.ds-traces-agent_builder.otel-default-*` (spans `invoke_agent`, `chat`, `execute_tool`; `attributes.gen_ai.tool.call.arguments/result`, `gen_ai.usage.input_tokens`). `script_fields` with `params['_source']['attributes']['gen_ai.tool.call.result'].length()` gives result sizes (LENGTH() on the field returns null for long values).
- Conversations: `api/agent_builder/conversations?agent_id=significant-events.discovery` (list, up to 1000), then `api/agent_builder/conversations/<id>` for rounds/steps (step types: tool_call, reasoning, compaction, substitution).
- Workflows: `.workflows-executions`, `.workflows-step-executions` (classify_detections output has reasons and baseline); detections `.significant_events-detections`; events `.rule-events*`; KIs `.significant_events-knowledge_indicators` (legacy docs use `stream.name`, newer `source.id`).
- ES|QL on a source view: `api/console/proxy?path=_query%3Fdrop_null_columns%3Dtrue&method=POST` with body `{"query":"FROM $.nightshift.sources.default.<slug> | ..."}`; `drop_null_columns` is a URL param, not a body field. Unfiltered LIMIT 5 on the agentless source can return millions of characters, always filter.
- Connectors: `internal/inference/connectors` (header `x-elastic-internal-origin: kibana`); the EIS luna connectors expose no contextWindowLength.
- Local helper scripts live in the session scratchpad and are not kept.
