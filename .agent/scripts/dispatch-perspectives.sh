#!/usr/bin/env bash
# dispatch-perspectives.sh — parallel perspective dispatch for crew-thinker degraded fallback.
# Environment variables: TASK_DIR (required), REPO_ROOT (required), TOPIC (required),
#   JOURNAL_CONTEXT_FULL (required), JOURNAL_CONTEXT_TOP5 (required)
# Called when both Agent tool and Task tool are unavailable.
# Note: These variables are set by the AI agent executing the preceding steps, not by literal shell.

if command -v claude &>/dev/null; then
  REPO_ROOT="$(git rev-parse --show-toplevel)"
  REPO="$(basename "$REPO_ROOT")"
  FAST_MODEL="${CLAUDE_FAST_MODEL:-sonnet}"
  DISPATCH_BASE="$HOME/.agent/thinker/$REPO"

  # Timeout: prefer GNU timeout, fall back to gtimeout (Homebrew), or skip
  if command -v timeout >/dev/null 2>&1; then TIMEOUT_CMD="timeout 180"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_CMD="gtimeout 180"
  else TIMEOUT_CMD=""; fi

  mkdir -p "$DISPATCH_BASE/personas"
  RUN_DIR="$(mktemp -d "$DISPATCH_BASE/personas/run-XXXXXXXXXX")"
  mkdir -p "$RUN_DIR/prompts" "$RUN_DIR/output"

  # Write two context files — connector gets the full 20-entry journal, others get top-5
  cat > "$RUN_DIR/context-full.txt" <<CTXEOF
**User profile:**
$(cat ~/.agent/PROFILE.md)

**Topic:**
$TOPIC

**Journal context:**
$JOURNAL_CONTEXT_FULL
CTXEOF

  cat > "$RUN_DIR/context-top5.txt" <<CTXEOF
**User profile:**
$(cat ~/.agent/PROFILE.md)

**Topic:**
$TOPIC

**Journal context:**
$JOURNAL_CONTEXT_TOP5
CTXEOF

  # Assemble prompt files — persona + separator + context + instruction
  for perspective in builder contrarian connector pragmatist; do
    context_file="$RUN_DIR/context-top5.txt"
    if [[ "$perspective" == "connector" ]]; then
      context_file="$RUN_DIR/context-full.txt"
    fi
    {
      cat "$REPO_ROOT/.cursor/agents/thinker-${perspective}.md"
      printf '\n\n---\n\n## Context\n\n'
      cat "$context_file"
      printf '\n\n---\n\nProduce your output now. Follow the output format in your persona definition.\n'
    } > "$RUN_DIR/prompts/${perspective}.txt"
  done

  # Parallel dispatch — indexed arrays for macOS Bash 3.2 compat
  NAMES=(builder contrarian connector pragmatist)
  PIDS=()
  for i in "${!NAMES[@]}"; do
    name="${NAMES[$i]}"
    model_flag=""
    case "$name" in
      pragmatist) model_flag="--model $FAST_MODEL" ;;
    esac
    $TIMEOUT_CMD claude -p $model_flag < "$RUN_DIR/prompts/${name}.txt" \
      > "$RUN_DIR/output/${name}.txt" 2>"$RUN_DIR/output/${name}.stderr" &
    PIDS+=($!)
  done

  # Collect — validate exit code + output content
  FAILURES=()
  for i in "${!NAMES[@]}"; do
    name="${NAMES[$i]}"
    if ! wait "${PIDS[$i]}"; then
      FAILURES+=("$name (exit $?)")
    elif [[ ! -s "$RUN_DIR/output/${name}.txt" ]]; then
      FAILURES+=("$name (empty output)")
    fi
  done

  # Read successful $RUN_DIR/output/*.txt and pass to Step 3 consolidation.
  # For failed perspectives, note the failure in the corresponding output section.
else
  # No dispatch mechanism — run perspectives inline sequentially.
  # Known degradation: ordering bias (later perspectives see accumulated context).
  exit 1
fi
