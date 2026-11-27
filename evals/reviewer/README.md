# Reviewer eval

Measures how often each reviewer persona and spec critic catches a known defect. Each case is a
small diff (or a small spec, for the critics) that hides one defect a real review found, labelled
with the lens that should catch it.

## Layout

| Path | Contents |
| --- | --- |
| `build_cases.py` | The source of every case; edit a case there, run it, and commit both |
| `cases/<id>/case.json` | Generated: the lens, the source, the change summary the persona reads, the hidden defect, where it is (`locations`, and `refs` for a spec), the keyword groups, the unchanged files (`context`) and the changed files after the change (`after`) |
| `cases/<id>/change.diff` or `spec.md` | Generated: what the persona reviews |
| `score.py` | Scores recorded replies; offline, no model call |
| `live.py` | The live run (opt-in, spends): dispatches personas and records their replies |
| `recorded/<label>/<persona>/<case>/run-<n>.md` | One reply per run, with `run-<n>.meta.json` (exit code, tainted paths) |
| `recorded/sample/` | Hand-written fixtures for the scorer's tests, not model output |

**Sources.** Cases are reduced from the persisted reviews and specs under `~/.agent/tasks/` (the task
and review are named in `source`), keeping only el-capitan code. A case with no persisted finding to
draw on, such as every critic case (critic replies are not persisted), is written by hand and says
`hand-seeded` in `source`. Nothing from another repository is copied; a defect seen elsewhere is
rebuilt as a synthetic equivalent and marked hand-seeded. A test checks that each `change.diff` agrees
with the case's `after` files line for line.

## Scoring

A run catches a case when one finding in the reply both:

- **anchors at the defect:** a `path:line` within 5 lines of one of the case's `locations` (an absolute
  or partial path counts). A range wider than 10 lines points at a region and locates nothing. For a
  spec case, a line number near a location, or one of the case's `refs` on the finding's first line,
  also counts;
- **names it:** every keyword group matches the finding's prose, with fenced and inline code removed
  (a quote of the change is not a description of what is wrong with it), as a whole word,
  case-insensitive. A trailing `*` makes a keyword a prefix. No group holds a word any finding could
  contain (`score.GENERIC_TERMS`), and a spec case has a second group naming the specific thing.

Findings start at a severity label (the reviewer contract) or a bold reference followed by a dash (the
critic contract). The last one ends at the blank line after its `Fix:` paragraph, or at a `Verdict:`
line, a heading or a `Files` line, so closing remarks are no part of it.

A persona's rate in one run is the share of its own lens's cases it caught. Its mean is over the runs,
reported with each run's rate and the spread, so the variance is visible. A missing reply and a tainted
run (one that touched a path outside its case) count as misses and are listed.

**The bar for a rewritten persona** (`score.py <run> --against <baseline>`, exit 1 when it fails, exit 2
when the baseline is not a directory or holds no replies): the candidate has at least the baseline's
number of runs, its mean is at least the baseline mean minus one baseline run's spread, and it catches
every case the baseline caught in all of its runs.

## Running

```bash
python3 evals/reviewer/score.py evals/reviewer/recorded/<label>            # score a recorded run
python3 evals/reviewer/score.py evals/reviewer/recorded/<new> --against evals/reviewer/recorded/<baseline>
python3 evals/reviewer/live.py                                              # the plan only: dispatches nothing
```

**The owner's baseline run** (opt-in: 24 cases x 3 runs = 72 persona sessions on the harness's model and
account; refused under `CI`; never run by the test suite):

```bash
python3 evals/reviewer/live.py --yes-spend --label baseline-$(date +%F)
```

The plan line says how many replies are already recorded and how many it will dispatch: a re-run with
the same label skips every `run-<n>.md` that holds a reply (`--redo` dispatches them again), and the run
stops with exit 3 after 3 failed dispatches in a row. A failed record keeps whatever the harness printed.

## Isolation

Each dispatch runs in a fresh scratch directory holding only the case's files, with the package on stdin:

```bash
claude -p --restricted --strict-mcp-config --disable-slash-commands --tools Read,Grep,Glob \
  --permission-prompts none --no-session-persistence --output-format stream-json --verbose \
  --agents '{"reviewer-<lens>": {"description": …, "prompt": <the persona file body>, "tools": ["Read", "Grep", "Glob"], "maxTurns": N}}' \
  --agent reviewer-<lens>
# environment: CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
```

The persona is defined from its source file in `.cursor/agents/`, not the installed copy, so it gets no
MCP servers. The package is the one a real run sends (the reviewer contract and the mode, or the critic
dispatch and contract), except that the lookups paragraph is replaced by one line: no code index or docs
server in this eval; use Read, Grep and Glob on the case files.

**What `claude --help` confirms:**

- `--restricted` ignores the user, project and local settings files, and confines the file tools to the
  working directories;
- `--strict-mcp-config` without `--mcp-config` loads no MCP server;
- `--disable-slash-commands` turns skills off;
- `--tools` limits the built-in tools.

**Not used:**

- `--bare` would skip hooks, CLAUDE.md and auto-memory, but it reads only `ANTHROPIC_API_KEY`, never the
  OAuth login.
- `--safe-mode` disables custom agents, which this run needs.

**Not confirmed:**

- whether `--restricted` also skips the user CLAUDE.md and its imports, and the hooks of plugins enabled
  outside the settings files;
- whether `--agents` honours `tools` and `maxTurns` exactly as frontmatter does.

**The backstop:** every tool call in the stream-json transcript with a path outside the scratch root,
and every `path:line` in the reply that cites one, is recorded in `run-<n>.meta.json` as `tainted`. A
tainted run is a miss.
