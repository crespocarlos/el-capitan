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
`evals/tools/test_*.py` for a single tool. Three suites create temporary git repositories and fail
inside the Cursor sandbox with `Operation not permitted`: `bash .claude/hooks/fixtures/run.sh`,
`python3 evals/tools/test_hooks_contract.py`, and `python3 evals/memory/run.py`. Run those with full
permissions, and check exit codes directly rather than piping to `tail`, which hides them.

## Hooks

Hook scripts under `.claude/hooks/` are shell, and the module ceiling does not apply to them — but
each one obeys the same contract, and the test that pins it is `evals/tools/test_hooks_contract.py`.
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
- **Pin both directions in the fixtures.** `.claude/hooks/fixtures/run.sh` is the verdict contract;
  a new rule adds its allow and deny cases there and to the contract test's per-hook matrix.

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
  lib/            cli.py files.py git.py git_remote.py  shared helpers: argparse factory, atomic write, git/gh
  task/           Task state, worktrees, progress and metric logging
  review/         Review pipeline: findings, layers, personas, report, hunk parsing
  memory/         Typed memory store and retrieval
  evals/          Eval inspection and comparison
  maintenance/    crew-lint and its lint_* families
```

Rules that the structural gate enforces:

- No module over 200 lines, in every package under `.agent/tools/` — `lib/`, `task/`, `review/`,
  `review/nightshift/`, `memory/`, `evals/`, and `maintenance/` alike. The capped set is derived from
  the tree, so a new package is capped without anyone remembering to add it. The entry point of a
  command stays under 120 and holds argument handling and exit codes only; logic lives in modules.
- No function over 50 lines. If it does not fit, the branch boundary inside it is a function.
- Every top-level function carries a return annotation.
- Four-space indent, no tabs, in every file.
- No comment block longer than four lines. Rationale belongs in the docstring of the thing it
  explains; the code should not carry its own history.
- **Git lives in `lib/git.py`.** No other Python module builds a `git` or `gh` argv, because a
  hand-rolled call reads empty output when git fails and then acts on it. Import the helper for the
  question — root, branch, remote, default branch, ancestry, blob, diff base — and let `GitError`
  reach the caller. `lib/git_remote.py` holds the network half and `git.py` re-exports it. Prompts
  follow the same rule in their own terms: a prompt asks a command (`crew-repo-info.py`,
  `crew-worktree.py`, `crew-diff.sh`), never git, and raw git stays only where the user approved a
  mutation. GitHub reads work the same way: a prompt asks `crew-pr-actions.py` for a PR, its diff, a
  repository, or an issue, and keeps raw `gh` only for a mutation or a search, because the hooks
  decide on the command text the caller wrote. Local reads use git alone; the network reads
  (`default_branch`, `fetch_remote`,
  `remote_tip`, `behind_count`) try `gh` first because it carries the authentication, fall back to
  git, and raise naming both. `evals/tools/test_python_shape.py` fails a git argv outside `lib/`.

## The task status contract

`task_status.py` owns the `## Status` value; nothing else parses it, and no writer invents a spelling.

- The states are `DRAFTING`, `APPROVED`, `IMPLEMENTING`, `ON-HOLD`, and `DONE`; `ABANDONED` is a
  user-only side state. They are uppercase, and a status may carry a suffix after the token
  (`ON-HOLD (auto-hold: …; was APPROVED)`).
- Reads normalize: `head` uppercases and strips trailing punctuation, so a legacy `done` and a
  `DONE` are one state. `token` rejects anything outside the set and names the allowed values, which
  is where a typo should fail rather than at a transition that silently matches no rule.
- Writers emit the canonical spelling. `DONE` is written only by `crew-ls.py --mark-done`, and the
  builder never writes a status at all; a hand-written value skips the gate that proves the review
  passed.
- `crew-ls.py --normalize-status [--apply]` is the migration for a legacy token: it reports each
  file, and a second run reports `0 of N` because a canonical value needs no change.

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
  is its only tool restriction. Claude Code reads `tools` and `maxTurns` and ignores `readonly`, so
  `maxTurns` binds under Claude Code only and every turn budget here is prose-enforced in Cursor.
  `tools` therefore speaks Claude Code ids, and each frontmatter says which harness reads which key.
  Do not set `model:`.
- **`readonly: true` is enforced, not copied.** `crew-lint`'s `missing-readonly` rule fails any agent
  under `.cursor/agents/` that omits it, except the workers named in `WRITE_CAPABLE_AGENTS` and the
  inline-only orchestrators named in `INLINE_ONLY_AGENTS`, both in `lint_prompts.py`. There are three
  workers: `crew-builder` and `crew-pr-resolver` write the change they were dispatched to make, and
  `reviewer-probe` writes one throwaway artifact, runs it, and deletes it. Add an exemption there when
  an agent must write, so the reason is reviewable rather than implied by an omission.
- **Backgrounding is a call-site field.** Set `run_in_background: true` on the dispatch that needs it;
  do not put `is_background` in frontmatter, which would state the same fact twice with no check that
  the copies agree.
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
