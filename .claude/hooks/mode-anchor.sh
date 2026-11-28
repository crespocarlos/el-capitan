#!/usr/bin/env bash
# mode-anchor.sh — the `prompt_submit` rule
# Emits a compact pipeline anchor each turn to prevent context drift on long conversations.
# Output is injected as system context before the model responds.
#
# The anchor is computed by `spec-status-reconcile.sh` at `SessionStart` and cached, so this hook does
# not resolve the task again every turn: it prints the cached line and recomputes only when the spec
# changed since the cache was written.
set -euo pipefail
HOOK_NAME=mode-anchor
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
# shellcheck source=lib/anchor.sh
. "$(dirname "$0")/lib/anchor.sh"
hook_input
anchor_current
