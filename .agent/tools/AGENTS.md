# Working with the Python tools

Guidance for any agent editing `.agent/tools/`. The repository root `AGENTS.md` covers the pipeline;
this file covers the code that pipeline runs.

## Run it, do not guess

```bash
python3 .agent/tools/maintenance/crew-lint.py --budget   # catalog, references, module cap, imports, budget
bash evals/ruff.sh check .                               # Ruff, the version pinned in ruff.toml
bash evals/test.sh -n auto                               # every test: pinned pytest + pytest-xdist (uvx)
uvx codespell==2.4.1 rules .cursor .claude/CLAUDE.md AGENTS.md README.md docs CONTRIBUTING.md SECURITY.md CHANGELOG.md .github .agent/tools/AGENTS.md .agent/tools/TOOLS.md
uvx --from vale==3.12.0.0 vale rules .cursor/agents .cursor/skills .claude/CLAUDE.md AGENTS.md README.md docs CONTRIBUTING.md SECURITY.md .agent/tools/AGENTS.md
```

The first two are fast and cover structure; codespell and Vale (pinned, the same lines CI runs) check
the spelling and the generic prose rules of prompts (`.vale.ini`, `.vale/styles/Crew`: emphasis
capitals, emoji, off-glossary terms), and crew-lint's `style` rules check the repo-specific writing
standard. `crew-lint.py --list-rules` prints every crew-lint rule;
Ruff (`ruff.toml`) owns generic Python style: imports, return annotations, function size (statements,
`PLR0915`), unused code, banned generic module names. `ruff.toml`'s `per-file-ignores` is a baseline
of existing violations: delete an entry when its file is clean, never add one for new code.
`ruff format` is not enforced yet. Behavioral changes also need the suite for the area you
touched — `evals/memory/run.py` for memory, `bash evals/test.sh evals/tools/test_<name>.py` for a
single suite (a test takes `tmp`, its own temporary directory, from `evals/conftest.py`). Suites that
create temporary git repositories fail inside the Cursor sandbox with `Operation not permitted`
(`test_hook_cases.py`, `evals/memory/run.py`). Run those with full permissions, and check exit codes
directly rather than piping to `tail`, which hides them.

## Hooks

Hook scripts under `.claude/hooks/` are shell, and the module ceiling does not apply to them — but
each one obeys the same contract, and the test that pins it is `evals/tools/test_hook_cases.py`.
Blocking is exit `2` with one line on stderr (Cursor gets its own JSON deny instead); no objection is
exit `0` with no output; an input a hook cannot read is one stderr line and exit `0`. A hook never
mixes the two blocking mechanisms, and only `guard/credentials.sh` fails closed, because only that
rule's failure is a credential leak. Cursor reads *silence* from a fail-closed hook as a failure, so
that one rule also prints an allow payload when it has no objection.

- **One rule per hook.** A new shell rule is its own file under `guard/`, registered on the Bash
  matcher in both settings files. It sources `lib/hook.sh` for the input, event, field, and
  deny/allow helpers rather than repeating the preamble.
- **Register it in both configs.** `crew-lint.py` fails an unregistered hook, and a file that is
  never registered is a guard that silently stopped guarding.
- **Keep each rule file under 60 lines.** Anything longer is two rules.
- **Pin both directions in the case tables.** `evals/tools/hook_cases.py` is the verdict contract;
  a new rule adds its allow and deny cases there, and a new hook file is classified in it.

## Language floor

The local interpreter is Python 3.9.6 and CI matches it. Two consequences:

- `X | None` in an annotation is a syntax error unless the module opens with
  `from __future__ import annotations`. Every module that uses it has that line; keep it.
- `match` statements do not parse. Use `if`/`elif`.

Standard library only. `requirements.txt` documents the deliberate absence of dependencies; adding one
is a change to that decision, not a routine edit.

## The catalog decides what exists

`.agent/tools/tools.json` is the source of truth for the command surface. Every entry carries `kind`:

| `kind` | Meaning | Installed |
|---|---|---|
| `command` | Something a person or prompt invokes | yes, linked into `~/.agent/bin` |
| `module` | Internal code imported by a command | never |
| `asset` | Data a command reads (query text, transitions) | never |

A new command needs a `tools.json` entry with `kind: command`, `category`, `owner`, `help`, and a
`smoke` line. A new module needs `kind: module` and must not be invoked. `install.sh` links commands
from the manifest rather than walking directories, so a file that is not in the catalog does not
install — and a module cannot leak into the command surface.

## Features that live inside existing commands

A feature that fits an existing command is a subcommand or a flag plus modules, never a new top-level
command (a command costs always-on router budget). What the hardening work added this way:

- `crew-verify.py` (`task_verify*.py`): the base branch's CI, run by the mirror of its `run:` steps
  (else the `AGENTS.md` `gates` block), as TOOLS.md "Gates and cost" describes. A target repo's optional `gates.json` only adds
  gates (a clash warns) and stands alone only as the sole source. The mirror never runs a release
  workflow, a job with `if:` or a publish command (`task_verify_sources.py`); `report-check`
  (`task_verify_report.py`) checks a builder report against the result.
- `crew-task.py` writes task state: `mark-approved|mark-implementing|mark-done` (`task_gates.py`),
  `reconcile [--apply]`, `normalize-status [--apply]`, `blocked`, `lock write|remove` (the
  `.crew-worker.lock` `guard/worker-tree.sh` reads; the builder is exempt through `CREW_WORKER_TASK`),
  `worktree pref|record` (`task_worktrees.py`) and `worktree check <tree>`
  (`task_worktrees.py`: `ok`, `on-feature-branch` exit 4, `dirty` exit 5), and `gc [--only telemetry]
  [--apply]` (`task_gc.py`: the retention policy of `~/.agent/config.json`). `crew-ls.py` only reads.
- `crew-ls.py` shows the REPO column, AGE from the last PROGRESS entry, `landed: yes|no|unknown|closed`, the
  `BLOCKED:` line and one `stale:` line; `--repo`, `--status`, `--cost`, `--watch [--interval N]`
  and `--report [--since 30d]` (`ls_report.py`), all over `ls_data.py`, the gathering a future TUI
  imports too; `crew-metric.py` validates `stage_start`, `stage_end` and `tokens_reported`
  (`task_progress.py`).
- `crew-doctor.py` (`doctor_checks.py`) is a command of its own because install health fits no
  existing command.
- `crew-review-findings.py save-out|consolidate` and `normalize --repo` (`review_render.py`,
  `review_consolidate.py`,
  `review_findings.py`); `crew-assemble-packages.py` records skips and optional slices
  (`assemble_inputs.py` decides, `assemble_build.py` slices and writes).
- New prose for these stages lives in `references/` files linked in one line (`stage-rules.md`,
  `worker-dispatch.md`), so the main prompt files stay under `MAX_PROMPT_FILE_BYTES`.
- `.github/workflows/validate.yml` runs `bash evals/test.sh -n auto` (pytest collects every
  `evals/tools/test_*.py` and `evals/reviewer/test_*.py`, `pytest.ini`) on ubuntu and macOS with
  Python 3.9 and 3.12, so a new suite there runs in CI with no workflow change.

## Settings a repository declares in its AGENTS.md

el-capitan is project-agnostic, so nothing about a target repo is guessed from its job names or
branch names: the repo opts in with a plain line in the `AGENTS.md` at its root (`worktree` is read
by `lib.files.agents_setting`; a line inside a fenced code block is not a setting). Every setting is
optional and the absence of each has one default.

| Setting | Format | Default when absent |
|---|---|---|
| `gates` | a fenced block, one `<name>: <command>` per line, `env: NAME=value` for shared variables | CI workflow steps are read first; with neither, `verify` says NOT VERIFIED |
| `landing_bases` | `landing_bases: ^\d+\.\d+$ ^\d+\.x$` (space separated), or a fenced `landing_bases` block, one pattern per line | the default branch is the only normal base |
| `worktree` | `worktree: true` | the worker branches off the default branch in the current checkout |
| `e2e` | `e2e: npm run e2e` (the script `crew-e2e` runs) | no e2e run; job names are never guessed |

- `landing_bases` patterns are regular expressions that must match the WHOLE branch name (`9.x`
  matches `^\d+\.x$`, `feat/9.x-fix` does not). A merged PR into a matching base is `landed: yes
  (backport to <base>)` in `crew ls`, and `crew open pr` opens against it without the stack message.
  Any other non-default base is still `no`.
- `verify` pins Node from the first of `.nvmrc`, `.node-version`, `.tool-versions` (`nodejs` line)
  and `package.json` `engines.node`; with none it prints "no Node pin found, using PATH" and leaves
  the PATH alone. CI it cannot read (`.buildkite/`, `.circleci/`, ...) is named ("CI not readable
  here (buildkite)") and skipped; the nearest `AGENTS.md` of each touched path may describe checks in
  prose, which `verify` prints as "repo-declared check, run this: <line>" and never runs.
- The worktree question is asked at most once per repo (see `worker-dispatch.md`): a recorded
  choice lives in `<git dir>/crew-worktree` and in a `WORKTREE:` line of the task's PROGRESS.md.

## Naming

- **Commands**: `crew-<kebab-case>.py`, for example `crew-review-findings.py`. The `crew-` prefix is
  what separates the command surface from internals.
- **Modules**: `<package>_<thing>.py`, for example `memory_store.py`, `review_layers.py`,
  `task_gates.py`. The package prefix keeps basenames unique across packages, which matters because
  all of them share one `~/.agent/bin` at depth one.
- **Sourced files** keep a plain name and are exempt from the prefix rule: `task-env.sh` must stay
  `task-env.sh` because `source` needs a real file at that exact path.
- A rename is a breaking change applied in one change. Do not add a compatibility wrapper for an old
  basename; update every caller instead. `.claude/hooks/`, `rules/`, and `.cursor/` are the caller
  surface, and `rg -n --hidden "agent/bin/" .cursor .claude rules install.sh` lists it.

## Module layout

```
.agent/tools/
  tools.json  TOOLS.md  requirements.txt   catalog and its documentation
  lib/            cli.py clock.py files.py git.py gh_reads.py next_steps.py output.py workflow_yaml.py  shared helpers (map: TOOLS.md)
  task/           Task state, worktrees, progress and metric logging
  review/         Review pipeline: findings, layers, personas, report, hunk parsing
  memory/         Typed memory store and retrieval
  evals/          Eval inspection and comparison
  maintenance/    crew-lint and its lint_* families
```

Rules that crew-lint enforces (crew-lint rule names in parentheses; the rest is Ruff):

- No module over 400 lines, entry points included, in every package under `.agent/tools/` and in
  `tui/` (`module-size`; `docstring-length` covers `tui/` too). The capped set is derived from the tree, so a new package is capped without
  anyone remembering to add it. An entry point holds argument handling and exit codes; logic lives
  in modules.
- No function over 50 statements (Ruff `PLR0915`). If it does not fit, the branch boundary inside it
  is a function.
- Every function carries a return annotation (Ruff `ANN201`/`ANN202`).
- A module docstring states the contract in at most 6 lines (`docstring-length`), and no docstring
  or comment narrates history: earlier behavior, measurements, incidents (`no-incident-narration`).
- No prompt, doc, hook or tool names a removed command form (`removed-command-form`).
- An import crosses packages only along an edge the `package-edges` block in TOOLS.md declares
  (`package-direction`).
- `atomic_write`, `gh`, `read_json_object`, `slug_from_url` and the UTC stamp are each defined once in the tree, and
  PROGRESS.md is touched only by `task/task_progress.py` (`single-owner`).
- **Git lives in `lib/git.py`** (`direct-git`). No other Python module builds a `git` or `gh` argv, because a
  hand-rolled call reads empty output when git fails and then acts on it. Import the helper for the
  question — root, branch, remote, default branch, ancestry, blob, diff base — and let `GitError`
  reach the caller. The network half (gh first, git second) lives in the same module. Prompts
  follow the same rule in their own terms: a prompt asks a command (`crew-repo-info.py`,
  `crew-worktree.py`, `crew-diff.sh`), never git, and raw git stays only where the user approved a
  mutation. GitHub reads work the same way: a prompt asks `crew-pr-actions.py` for a PR, its diff, a
  repository, or an issue, and keeps raw `gh` only for a mutation or a search, because the hooks
  decide on the command text the caller wrote. Local reads use git alone; the network reads
  (`default_branch`, `fetch_remote`,
  `remote_tip`, `behind_count`) try `gh` first because it carries the authentication, fall back to
  git, and raise naming both. `crew-lint` (`direct-git`) fails a git argv outside `lib/`.

## Imports

Every package directory (`task/`, `review/`, `memory/`, `evals/`, `maintenance/`) holds a
byte-identical `<package>_bootstrap.py`. It finds `.agent/tools` from its own resolved path and puts
that root (so `lib.*` imports) and every package directory on `sys.path`. An entry point runs
through a symlink in `~/.agent/bin` from any cwd, and Python puts the script's resolved directory
first on `sys.path`, so the first import below the standard library finds the bootstrap:

```python
import task_bootstrap  # noqa: F401  (sets the import path; must precede the sibling imports)
from task_status import STATUS
from lib.git import run_git
```

The contract: **entry points** import their package's `<package>_bootstrap` first; **library
modules** do not, and rely on the entry point (or the test) that loaded them having set the path;
`lib/` is always imported as `lib.*`. **A test that loads a module by path** puts `.agent/tools` and
that module's package directory on `sys.path`. Which package may import which is the `package-edges`
block in TOOLS.md (crew-lint `package-direction`). Nothing else touches `sys.path` (Ruff `TID251`;
crew-lint `bootstrap-identical` fails a bootstrap copy that drifts), so Ruff's `E402` never needs a
`# noqa`, and a module never runs a sibling `crew-*.py` as a process to reach its logic
(`no-sibling-subprocess`): it imports the module that holds it.

## The task status contract

`task_status.py` owns the `## Status` value; nothing else parses it, and no writer invents a spelling.

- The states are `DRAFTING`, `APPROVED`, `IMPLEMENTING`, `ON-HOLD`, and `DONE`; `ABANDONED` is a
  user-only side state. They are uppercase, and a status may carry a suffix after the token
  (`ON-HOLD (auto-hold: …; was APPROVED)`).
- Reads normalize: `head` uppercases and strips trailing punctuation, so a legacy `done` and a
  `DONE` are one state. `token` rejects anything outside the set and names the allowed values, which
  is where a typo should fail rather than at a transition that silently matches no rule.
- Writers emit the canonical spelling. `DONE` is written only by `crew-task.py mark-done`, once a PR
  for the task is open, and the builder never writes a status at all; a hand-written value skips the
  gate that records the PR and checks the criteria and the reviewed commit.
- A task's PR list is the PR URLs in its PROGRESS.md (`task_progress.pr_urls`): the `PR opened:` of
  its DONE transition and a `PR:` entry for each later one. `mark-done` and `reconcile --apply`
  (which reads each IMPLEMENTING task's branch PR with `gh pr list --head`, cached for a day and
  bounded at session start, `task_prs.py`) append through
  `task_progress.append_pr`; the issue is the spec's `Issue:` line, else its first issue URL.
- `crew-task.py normalize-status [--apply]` is the migration for a legacy token: it reports each
  file, and a second run reports `0 of N` because a canonical value needs no change.

## Exit codes

The contract is uniform, with the exceptions listed below it, and callers depend on it:

| Code | Meaning |
|---|---|
| `0` | Success, including "nothing to do" |
| `1` | The command ran and found a problem (lint finding, failed check) |
| `2` | Invalid invocation, or the infrastructure the command needs is unavailable |

Every other code is a named `EXIT_*` constant in its source module and has one row here
(`evals/tools/test_command_names.py` checks both ways; a bare `return 3` fails it):

| Command | Code | Meaning | Source |
|---|---|---|---|
| `crew-verify.py` | `3` | NOT VERIFIED: every gate passed, but the run was partial (mirror steps skipped) or only prose checks exist (each `2` with `--strict`) | `task/task_verify_env.py` |
| `crew-verify.py --wait` | `4` | still running when `--wait-timeout` ran out; do not hand off | `task/task_verify.py` |
| `crew-task.py worktree check` | `4` | on a feature branch: use it as is | `task/task_worktrees.py` |
| `crew-task.py worktree check` | `5` | the tree is dirty | `task/task_worktrees.py` |
| `crew-mem.py add` | `3` | duplicate candidates found; nothing written (`--force` writes) | `memory/memory_add.py` |
| `crew-mem.py import-inbox` | `3` | every draft was a duplicate; nothing imported | `memory/memory_inbox.py` |
| `crew-nightshift-e2e.py` | `3` | the server did not answer on its port | `review/crew-nightshift-e2e.py` |

A command that cannot proceed says why on stderr and exits `2`: `lib.cli.fail(message)`, never
`raise SystemExit("message")`, which exits `1` (crew-lint `no-systemexit-str`). Parsers are plain
`argparse.ArgumentParser(...)`, a required subcommand group `parser.add_subparsers(dest=...,
required=True)`. Silence with `0` is reserved for a genuinely empty result, and a command that reports "nothing found" must be distinguishable from one
that failed to look.

## Output

- Human-facing commands print a table or prose to stdout.
- Anything an agent parses offers `--json`: valid JSON on stdout, diagnostics on stderr, nothing else
  interleaved.
- Output that can grow without bound accepts `--max-chars` or `--limit`. Truncation prints a marker
  naming what was dropped and how to get the rest — never truncate silently, because a model that
  receives a cut list assumes it was complete.

## Glossary

One term per concept across every rule, agent, skill and reference (Vale's `Crew.Glossary` fails the
off-glossary synonyms it knows; crew-lint `glossary-terms` keeps this the one glossary). Load the
`prompt-authoring` skill.

| Term | Meaning |
| --- | --- |
| persona | A dispatched reviewer or critic: one lens over one artifact, read-only (`reviewer-*`, `specwriter-scope`, `specwriter-adversarial`); the explorers are personas too |
| orchestrator | `crew-reviewer` or `crew-specwriter`, run inline in the main session; it dispatches personas |
| worker | A dispatched agent that produces the stage's work: `crew-builder` (writes) or `crew-pr-resolver` (read-only analysis) |
| gate | A user approval only: Gate 1 approves SPEC.md, Gate 2 approves the PR in `crew open pr` |
| verification | The checks a stage runs (tests, lint, `crew-verify.py`); never called a gate |
| label | A finding's severity, from the one table in `.cursor/agents/references/reviewer-contract.md`, which covers code, spec and idea modes |
| closing confirmation | The build workflow's one journal and memory question, asked after `crew open pr` opens the PR; the respond workflow's is `crew-pr-resolver`'s `+ journal` |

## Authoring agent and skill files

- **Frontmatter keys are harness-specific.** Cursor reads `name`, `description`, `readonly`, and
  `is_background`; it ignores `tools` and `maxTurns` and inherits every parent tool, MCP included,
  so `readonly: true` is its only tool restriction. Claude Code reads `tools` and `maxTurns` and
  ignores `readonly`, so `maxTurns` binds under Claude Code only and every turn budget here is
  prose-enforced in Cursor. `tools` therefore speaks Claude Code ids. These notes live here once; an
  agent's frontmatter carries no harness comments. Do not set `model:`.
- **A dispatched agent has an allowlist; the docs and code-search servers come from the config.** A
  deny list cannot keep out claude.ai connectors, plugin servers or tools the harness adds later, so
  each dispatched agent's `tools:` line names exactly its class's native tools and ends with the YAML
  comment `  # {{mcp_servers}}`, so the source line is valid by itself. Install replaces the comment
  with one `, mcp__<server>__*` per server named in `mcp.docs` and `mcp.code_search` of
  `~/.agent/config.json` (removes it when none is), writing the agent into `~/.cursor/agents` as a
  regular file instead of a link, recorded in the install manifest (`rendered_agents`) and removed by
  uninstall; the SessionStart hook `agents-refresh.sh` rewrites a copy gone stale, and `crew doctor`
  fails one still stale. The classes are `AGENT_CLASSES` in `lint_prompts.py`, and `crew-lint`'s
  `agents-inherit-tools` fails any other line, a missing placeholder, or a `disallowedTools`:
  - **Read-only class** (`READONLY_AGENT_TOOLS`, every persona, explorer and critic): `Read, Grep, Glob`.
  - **`crew-pr-resolver`** (`RESOLVER_AGENT_TOOLS`): plus `Bash`, for `gh` reads and probes.
  - **`reviewer-probe`** (`PROBE_AGENT_TOOLS`): plus `Write` and `Bash`, for its throwaway artifact.
  - **`crew-builder`** and the inline orchestrators: no `tools:` line; they inherit.

  With Bash, "never edits, pushes or posts" (the resolver) and "no edit outlives the run" (the probe)
  are instructions, not denies. Every native id resolves against `native_tools` in `tools.json`
  (`tool-id-unknown`), so a typo fails. The configured servers are assumed read-only (search, read and
  list tools); name only such servers in `mcp`.
- **`readonly: true` is enforced, not copied.** `crew-lint`'s `missing-readonly` rule fails any agent
  under `.cursor/agents/` that omits it, except the classes `AGENT_CLASSES` in `lint_prompts.py`
  exempts. There are two workers: `crew-builder` writes the change it was dispatched to make, and
  `reviewer-probe` writes one throwaway artifact, runs it, and deletes it; `crew-reviewer` and
  `crew-specwriter` run inline, where `readonly` never applies. `crew-pr-resolver` is a read-only
  analysis subagent; the main session creates its worktree before dispatch and applies the plan it
  returns as its final message. It keeps Bash for `gh` reads and probes, so in Claude Code, which
  ignores `readonly`, its read-only promise holds by instruction only. Add a class there when an
  agent must write, so the reason is reviewable rather than implied by an omission.
- **Backgrounding is a call-site field.** Set `run_in_background: true` on the dispatch that needs it;
  do not put `is_background` in frontmatter, which would state the same fact twice with no check that
  the copies agree.
- **Tool ids resolve against the catalog.** `crew-lint` checks every `mcp__<server>__<tool>` id
  against `mcp_servers` and every native `tools:` id against `native_tools` in `tools.json`; register
  a new one there, never only in prose.
- **Skill files** follow the workflow header, execution model, numbered steps shape;
  `crew-commit/SKILL.md` is the canonical example. Material a step needs only sometimes goes in
  `references/` and is linked, not inlined. An agent or skill file stays under 11,500 bytes.
- **A handoff trailer is one line.** A file that hands work on ends with `> Next: ` naming the
  `crew <verb>` to run next — once, as the last non-empty line, resolvable in `crew-router.mdc`.
  `crew-lint` enforces the shape; several outcomes are quoted per branch instead.

## Editing and tests

Text changes follow the root `AGENTS.md` "Editing" section. When adding tests: the area's file is in `evals/tools/` or `evals/reviewer/` (one file per tool or
family), hermetic (no network, no API key); CI runs every `test_*.py` there. Run a command in process
with `evals/tools/cli_runner.py` unless the test is about the process itself; the runner shares imported
modules between calls, so a tool reads HOME and the environment at call time, never at import.
Otherwise follow `~/.cursor/agents/references/testing-policy.md`.
