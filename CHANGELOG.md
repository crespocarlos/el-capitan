# Changelog

All notable changes to el-capitan are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- **Wave 1 — Correctness & Safety**
  - Hook bypass protection: PreToolUse check-write-boundary guard prevents accidental edits outside the active worktree
  - settings.json merge: install.sh deep-merges hooks instead of overwriting user config
  - maxTurns increase: persona subagents raised to allow sufficient exploration depth
  - Timestamp seconds: PROGRESS.md entries now include HH:MM:SS for precise sequencing
  - Diff verdict: crew-diff produces a clear PASS/FAIL verdict line for autopilot gating
  - Routing sync annotations: crew-router.mdc explicitly notes CLAUDE.md as a sync target
  - SPEC status validation: crew status warns on unknown status values

- **Wave 2 — UX, Polish & New Capabilities**
  - `crew health`: inline health check command with five checks (symlinks, hooks, jq, gh auth, active SPEC.md) and a version check; auto-runs when crew status finds no active task
  - `crew abandon`: graceful task abandonment skill — stashes changes, logs ABANDONED to PROGRESS.md, writes SESSION.md stub
  - PR resolver improvements: outdated thread triage (separate read-only section), pagination loop for large PRs, re-entry hint after applying changes
  - Worktree collision guard: manage-worktree.sh detects directory name collisions and either errors (different branch) or appends a hash suffix (unregistered directory)
  - Persona context authority note: all 9 reviewer/thinker persona files now declare source material authority upfront
  - crew-reviewer project mode: reviews README, orchestrator, and router when no diff relative to main
  - Truncation signal: crew-reviewer and crew-thinker emit a warning when any persona response is fewer than 80 words
  - README documentation pass: Quick Start clarification, state storage note, ralph section, PROFILE.md section, macOS prerequisites note, data & privacy section, Extending / Add-ons section
  - Session logger: new `.claude/hooks/session-logger.sh` writes per-tool JSONL entries to `~/.agent/sessions/`
  - Scope snapshot: crew-implement captures a BASELINE.diff; crew-commit warns on out-of-scope file modifications
  - macOS notification guard: osascript hook wrapped in uname check, silent on non-macOS
  - CHANGELOG: this file
