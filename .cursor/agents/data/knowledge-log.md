# Knowledge Log

This file is the memory of your creative-buddy agent. It's written to automatically after every session.

**Don't edit the entries manually** — but do fill in the Profile section below. The more honest it is, the more useful the agent becomes.

---

## My Profile

```
WHO I AM:
Software engineer at Elastic working on Kibana. Focused on the observability/streams
space — synthetic data generation, LLM feature extraction, and eval infrastructure.
Also actively building personal AI tooling (Cursor agents, skills, automation workflows).

WHAT I'M BUILDING / WORKING ON:
- SigEvents: deterministic synthetic log generator + LLM evals for significant events
  feature in Kibana (kbn-synthtrace, kbn-evals-suite-streams)
- Cursor agent/skill system: learning pipeline (@learn/@understand), creative pipeline
  (@creative-buddy), PR review automation, code suggestion reviewer skill
- Exploring multi-agent patterns for dev workflows

HOW I THINK:
Builder — I learn by making things. I engage with theory only when it unlocks something
I can ship. I like short feedback loops and get bored of pure exploration fast.
Pragmatist: I want the shortest path to something that works, then I'll refine.

WHAT I'M TRYING TO GET BETTER AT:
- LLM eval design: how to measure what matters, ground truth from config, snapshot fidelity
- AI agent workflows: when to use skills vs subagents, how to chain them well
- Using AI tooling (Cursor, agents) more effectively in my daily engineering work

RECURRING THEMES I'M INTERESTED IN:
- Ground-truth-from-config patterns (declare the topology, derive the expectations)
- Determinism in synthetic/test data generation
- Multi-agent systems for developer workflows
- Schema-first observability (OTel Weaver, semantic conventions)
```

---

## Entries

<!-- Agent writes below this line automatically -->

---
## 2026-02-27 — AI Crew (multi-agent dev system) — what could I do with it?

**Source/Topic:** https://github.com/amirilovic/ai-crew
**Key idea:** Multi-agent crew (PO, Dev, QA, Architect) collaborating via Discord + GitHub is a template you can use directly, customize (new agents, integrations), or adapt to non-software domains (research, content, data).
**Connections made:** None yet (first substantive entry)
**Experiments queued:** (1) Fork and run on tiny project, (2) Add Summarizer agent, (3) Repurpose for non-code output e.g. blog post
**Patterns emerging:** User exploring AI tooling/automation; interest in practical applications over theory
**Open questions:** Where do you want to be in the loop? Smallest useful crew? Which non-software domain would you actually use?

---
## 2026-02-27 — SigEvents: deterministic synthetic log generator for LLM feature extraction

**Source/Topic:** kbn-synthtrace `src/lib/sigevents` (Kibana)
**Key idea:** Declared service graph topology is the ground truth; expected features are derivable from the same config. No hand-authored eval expectations needed. Deterministic via mulberry32(seed).
**Connections made:** Synthtrace (synthetic data), observability (logs, traces, infra), LLM evals, kbn-evals-suite-streams (sigevents snapshots)
**Experiments queued:** (1) Add a new failure scenario to claims, (2) Create ecommerce mock app, (3) Use buildLogsGenerator in eval fixture without ES
**Patterns emerging:** Ground-truth-from-config pattern for eval; template pools + placeholders; phase-driven failure injection
**Open questions:** How does the eval pipeline consume manifest + docs? What's the fidelity gap vs real OTEL?

---
## 2026-02-27 — OpenTelemetry Weaver: Observability by Design

**Source/Topic:** https://github.com/open-telemetry/weaver, https://opentelemetry.io/blog/2025/otel-weaver/
**Key idea:** Weaver is a CLI/platform for managing semantic conventions—define, validate, live-check, codegen, diff. Treat telemetry like a public API. Registry = YAML schema; Rego policies; Jinja templates; live-check validates emitted OTLP vs schema; emit generates sample telemetry for dashboards.
**Connections made:** OTel semantic conventions, observability tooling, schema-first workflows
**Experiments queued:** (1) Run `weaver registry check` on OTel registry, (2) Create minimal custom registry (ToDo-style), (3) Use `weaver emit` for dashboard dev
**Patterns emerging:** Schema-first observability; shift-left validation; semantic conventions as shared grammar (900+ attributes, 70+ domains)
**Open questions:** None
