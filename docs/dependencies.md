# Dependencies

Every dependency is pinned in `pyproject.toml` and `uv.lock`, replaces code el-capitan would otherwise
maintain or does the job measurably better, and never loads on a hook or hot command path. One line each.

| Dependency | Group | Why |
|---|---|---|
| PyYAML | runtime | Replaces the hand-written workflow reader (`lib/workflow_yaml.py`) and the frontmatter regexes; loaded only by crew-lint, crew-doctor and crew-verify |
| Textual | `tui` | The dashboard's terminal UI; never installed into `~/.agent/venv` |
| pytest, pytest-xdist, pytest-timeout | `dev` | The test runner, parallel workers and the per-test timeout |
| basedpyright | `dev` | Pyright with a baseline file, so type errors only shrink |
