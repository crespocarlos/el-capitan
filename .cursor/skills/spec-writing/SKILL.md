---
name: spec-writing
description: "Write an implementation-ready spec (summary, acceptance criteria, tests, tasks) for a feature, bug fix, or refactor. Use when the user asks to write, draft, or plan a spec or implementation plan. Works standalone; `crew spec` wraps it with task state, critics, and an approval gate."
---

# Spec writing

Produce one spec that an engineer or coding agent can implement without re-exploring the codebase.
This skill is harness-neutral: it needs file read/search tools and, optionally, a
structured-question tool.

## Inputs

- The request: an issue (URL, number, or pasted text) or a plain description.
- Output path: the caller's path if given; otherwise `docs/specs/<slug>.md` in the repository, where
  `<slug>` is the lowercase, hyphenated title (≤50 characters). Confirm the path before writing when
  the directory does not exist.
- Template: `references/bug-spec-template.md` when the request has reproduction steps, a `bug`
  label, or words such as "broken", "regression", "error", or "crash"; otherwise
  `references/spec-template.md`. Outside a pipeline that tracks state, omit the `Branch` and
  `Status` lines.

## Step 1: Research the code as it is

Turn the request into 3–6 concrete research questions (where X lives, how Y is done today, which
tests cover Z, which quality gates run). Answer them from the code, not from the request: describe
what exists, with `path:line` pointers, and do not propose changes yet. Collect:

- files and modules involved;
- one or two canonical examples of the same kind of change, with 5–20 line excerpts;
- test files and the exact commands that run them;
- lint, type-check, and other quality-gate commands from the repository's agent or contributor
  guide.

Verify claims about external APIs, query languages, or library behavior against official
documentation before relying on them.

## Step 2: Clarify before drafting

List the unknowns that would change acceptance criteria, scope, or a public contract. Rank them by
impact × uncertainty and ask at most three, in one batch. Each question is multiple choice, names
the recommended option first, and states what breaks if the guess is wrong. Use the harness's
structured-question tool when available. Do not ask what the code or request already answers. Skip
this step when nothing qualifies.

Record any unknown still unresolved after the answers as `[NEEDS CLARIFICATION: …]` under `## Open
questions`. A spec with open items is a draft, not a plan.

## Step 3: Draft

- **Summary** — problem, scope, and goal in 1–2 paragraphs. `Out of scope:` names the adjacent work
  a reader would expect, each with a one-phrase reason. Link the issue.
- **Acceptance criteria** — a flat checkbox list, inferred from the request rather than invented.
  Write behavior as `WHEN <trigger> THEN <observable outcome>`. Every criterion names its check: a
  command, or a file plus what to inspect. Structural constraints (boundaries, API surface, pattern
  reuse) and non-regression items are criteria too.
- **Tests** — keep only the layers that apply (`### Unit`, `### Integration`, `### E2E`, `###
  Validation`); each kept layer has a runnable `**Command**`. Quality gates go under `###
  Validation`.
- **Tasks** — ordered, one architectural unit each (a function, module, or file pair), touching 1–2
  files. Each task says what to change and where (paths from the repository root, never `./`), and
  ends with `Verify: <command>` or `Verify: inspect: <what>`. Split any "modify X to also do Y"
  task. Declare tasks that must land together: `> Tasks N and N+1 are atomic — commit together.` Add
  a final documentation task when the change alters a concept, stage, command, or constraint that
  existing docs describe.
- **Hints** — optional; at most four short canonical excerpts where an implementer would otherwise
  guess wrong.

Keep the spec lean: include only what is needed to implement correctly.

## Step 4: Self-check

Fix every failure before presenting:

1. One PR: no group of tasks that could ship independently with no dependency on the rest.
2. Every criterion maps to at least one task, and every task serves a criterion.
3. Every criterion has a pass/fail check; no "appropriate", "properly", "fast", or "as needed"
   without a threshold.
4. Unhappy paths are covered for each behavior: empty input, missing resource, dependency failure,
   partial failure, concurrency where relevant.
5. Assumptions about services, environment, ordering, and permissions are stated.
6. Every verify command runs from the repository root without state from an earlier task, or the
   dependency is explicit.
7. API, UI, or cross-layer changes have an `### Integration` or `### E2E` layer, or the Summary says
   why not.

## Step 5: Present

Write the file. Report the path, a plain-language summary of what will be built, the acceptance
criteria, and any open questions. Stop: do not implement.
