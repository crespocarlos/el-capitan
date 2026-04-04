#!/usr/bin/env bash
# dispatch-critics.sh — parallel critic dispatch for crew-specwriter degraded fallback.
# Environment variables: TASK_DIR (required), REPO_ROOT (required)
# Called when both Agent tool and Task tool are unavailable.
# Note: Variables like $TASK_DIR and $REPO_ROOT must be set by the caller.

if command -v claude &>/dev/null; then
  FAST_MODEL="${CLAUDE_FAST_MODEL:-sonnet}"
  DISPATCH_BASE="$TASK_DIR"

  if command -v timeout >/dev/null 2>&1; then TIMEOUT_CMD="timeout 180"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_CMD="gtimeout 180"
  else TIMEOUT_CMD=""; fi

  mkdir -p "$DISPATCH_BASE/personas"
  RUN_DIR="$(mktemp -d "$DISPATCH_BASE/personas/run-XXXXXXXXXX")"
  mkdir -p "$RUN_DIR/prompts" "$RUN_DIR/output"

  for critic in scope adversarial implementer; do
    {
      cat "$REPO_ROOT/.cursor/agents/specwriter-${critic}.md"
      printf '\n\n---\n\n## Critique context\n\nYou are reviewing a draft SPEC.md before it is presented to the user.\nFind problems — do not suggest rewrites. The specwriter will apply fixes.\n\n## Draft spec\n\n'
      cat "$TASK_DIR/SPEC.md"
      printf '\n\n---\n\nProduce your critique now. Follow the output format in your persona definition.\n'
    } > "$RUN_DIR/prompts/${critic}.txt"
  done

  NAMES=(scope adversarial implementer)
  PIDS=()
  for i in "${!NAMES[@]}"; do
    name="${NAMES[$i]}"
    model_flag=""
    case "$name" in scope|implementer) model_flag="--model $FAST_MODEL" ;; esac
    $TIMEOUT_CMD claude -p $model_flag < "$RUN_DIR/prompts/${name}.txt" \
      > "$RUN_DIR/output/${name}.txt" 2>"$RUN_DIR/output/${name}.stderr" &
    PIDS+=($!)
  done

  FAILURES=()
  for i in "${!NAMES[@]}"; do
    name="${NAMES[$i]}"
    if ! wait "${PIDS[$i]}"; then FAILURES+=("$name (exit $?)")
    elif [[ ! -s "$RUN_DIR/output/${name}.txt" ]]; then FAILURES+=("$name (empty output)"); fi
  done
else
  # No dispatch mechanism — run critics inline sequentially.
  # Known degradation: ordering bias (later critics see accumulated context).
  exit 1
fi
