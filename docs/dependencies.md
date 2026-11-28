# Dependencies

Every dependency is pinned in `pyproject.toml` and `uv.lock`, replaces code el-capitan would otherwise
maintain or does the job measurably better, and never loads on a hook or hot command path. One line each.

| Dependency | Group | Why |
|---|---|---|
| PyYAML | runtime | Replaces the hand-written workflow reader (`lib/workflow_yaml.py`) and the frontmatter regexes; loaded only by crew-lint, crew-doctor and crew-verify |
| shfmt-py | runtime | Bundles shfmt v3.14.1, the guards' bash parser, into `~/.agent/venv`; replaces the 290-line awk parser in `.claude/hooks/lib/hook.sh` and its separate binary install. A binary, never imported |
| Textual | `tui` | The dashboard's terminal UI; never installed into `~/.agent/venv` |
| pytest-textual-snapshot | `tui` | SVG snapshots of each dashboard tab at 80×24 and 160×48, in place of hand-written screen assertions |
| pytest, pytest-xdist, pytest-timeout | `dev` | The test runner, parallel workers and the per-test timeout |
| basedpyright | `dev` | Pyright with a baseline file, so type errors only shrink |

**Measured and not adopted.**
- **githubkit 0.13.3** (with pydantic 2.14), for the GitHub reads (`lib/gh_reads.py`, `review_pr_reads.py`, the PR
  lookups in `task_prs.py`, the PR-head GraphQL fetch in `review_head.py`): 44 MB installed, 92 ms to import. The `gh`
  JSON plumbing it would replace is about 140 lines, and an equivalent client with its `gh auth token` setup is about
  100, so code would shrink by about 40 lines; but every GitHub test stubs `gh` on PATH (`test_pr_reads.py`,
  `test_prepare.py`, `test_ship.py`, `test_landed.py`, the TUI facts), so the tests would grow an HTTP mock layer, and
  the resolver's mutations stay literal `gh` either way. Not adopted; revisit when the MCP path (Phase 5b) loads
  pydantic anyway.
- **cyclopts 5.5.3 and Typer 0.29.3**, for `crew-tool.py`'s command line built from the verb signatures. Import time,
  median of five: argparse 4.5 ms, cyclopts 28.4 ms (with attrs, docstring-parser, rich, rich-rst), Typer 22.7 ms
  (with pydantic, rich, shellingham); 19 MB installed for both. `repo-facts --field branch` costs 51.3 ms (median of
  21) with the stdlib adapter in a clean checkout, so either library would put it at about 70-75 ms, past the 70 ms
  `bench_tools.py` budget. The stdlib adapter is 37 lines (`parameters`, `add_arguments`); neither library removes the
  envelope, `--field` or the one-line usage error, so the saving is under 30 lines. Not adopted: the adapter reads
  the same typed signatures and docstrings an MCP server registers (Phase 5b).
- **gitleaks-py**: an unvetted third-party wrapper; gitleaks stays the pinned, checksum-verified release binary
  (`scripts/install-bin.sh`).
