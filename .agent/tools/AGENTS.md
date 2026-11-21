# Working with the Python tools

Guidance for any agent editing `.agent/tools/`. The repository root `AGENTS.md` covers the pipeline;
this file covers the code that pipeline runs.

## Run it, do not guess

```bash
python3 .agent/tools/maintenance/crew-lint.py --budget   # catalog, references, naming, token budget
python3 evals/tools/test_python_shape.py                 # typing, function size, indent, comments
python3 evals/tools/test_command_names.py                # catalog kinds, installed link set
```

The three are fast and cover structure. Behavioral changes also need the suite for the area you
touched — `evals/memory/run.py` for memory, `evals/reviewer/test_*.py` for review,
`evals/tools/test_*.py` for a single tool. Two suites create temporary git repositories and fail
inside the Cursor sandbox with `Operation not permitted`: `bash .claude/hooks/fixtures/run.sh` and
`python3 evals/memory/run.py`. Run those with full permissions, and check exit codes directly rather
than piping to `tail`, which hides them.

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
  lib/            cli.py files.py git.py    shared helpers: argparse factory, atomic write, gh runner
  task/           Task state, worktrees, progress and metric logging
  review/         Review pipeline: findings, layers, personas, report, hunk parsing
  memory/         Typed memory store and retrieval
  evals/          Eval inspection and comparison
  maintenance/    crew-lint and its lint_* families
```

Rules that the structural gate enforces:

- No module over 200 lines. The entry point of a command stays under 120 and holds argument handling
  and exit codes only; logic lives in modules.
- No function over 50 lines. If it does not fit, the branch boundary inside it is a function.
- Every top-level function carries a return annotation.
- Four-space indent, no tabs, in every file.
- No comment block longer than four lines. Rationale belongs in the docstring of the thing it
  explains; the code should not carry its own history.

## Exit codes

The contract is uniform and callers depend on it:

| Code | Meaning |
|---|---|
| `0` | Success, including "nothing to do" |
| `1` | The command ran and found a problem (lint finding, failed check) |
| `2` | Invalid invocation, or the infrastructure the command needs is unavailable |

A command that cannot proceed says why on stderr and exits `2`. Silence with `0` is reserved for a
genuinely empty result, and a command that reports "nothing found" must be distinguishable from one
that failed to look.

## Output

- Human-facing commands print a table or prose to stdout.
- Anything an agent parses offers `--json`: valid JSON on stdout, diagnostics on stderr, nothing else
  interleaved.
- Output that can grow without bound accepts `--max-chars` or `--limit`. Truncation prints a marker
  naming what was dropped and how to get the rest — never truncate silently, because a model that
  receives a cut list assumes it was complete.

## Authoring agent and skill files

- **Frontmatter keys are harness-specific.** Cursor reads `name`, `description`, `readonly`, and
  `is_background`; it ignores `tools` and `maxTurns` and inherits every parent tool, so `readonly: true`
  is its only tool restriction. Claude Code reads `tools` and `maxTurns` and ignores `readonly`.
  `tools` therefore speaks Claude Code ids, and each frontmatter says which harness reads which key.
  Do not set `model:`.
- **Tool ids resolve against the catalog.** `crew-lint` checks every id against `mcp_servers` and
  `native_tools` in `tools.json`; register a new one there, never only in prose.
- **Skill files** follow the workflow header, execution model, numbered steps shape;
  `crew-commit/SKILL.md` is the canonical example. Material a step needs only sometimes goes in
  `references/` and is linked, not inlined. An agent or skill file stays under 12,000 bytes.

## Editing

Use the edit or write tool for every text change. A `python3 - <<'PY'`, `sed -i`, or redirect that
rewrites a file bypasses the review diff and turns a wrong anchor into a silent no-op.

When adding tests: put an area's tests in `evals/`, one file per tool or family, hermetic (no network,
no API key), and register the file in `.github/workflows/validate.yml`. Test the message text and exit
codes callers rely on; those are the contract.
