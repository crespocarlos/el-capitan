#!/usr/bin/env bash
# dispatch-reviewers.sh — parallel reviewer dispatch for crew-reviewer degraded fallback.
# Environment variables required:
#   TASK_DIR       — active task directory
#   REPO_ROOT      — git repo root (defaults to git rev-parse --show-toplevel)
#   REVIEW_MODE    — "self", "pr", or "spec"
#   DIFF_CONTENT   — the diff or spec text to review (pass via env or stdin)
# Called when both Agent tool and Task tool are unavailable.

set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"
REPO="$(basename "$REPO_ROOT")"
BRANCH="$(git branch --show-current)"
FAST_MODEL="${CLAUDE_FAST_MODEL:-sonnet}"

# Full reviewer list — all personas always dispatched
REVIEWERS=(code-quality adversarial fresh-eyes architecture product-flow)
FAST_REVIEWERS=(code-quality product-flow)

if ! command -v claude &>/dev/null; then
  echo "dispatch-reviewers: claude not on PATH — run reviewers inline" >&2
  exit 1
fi

if command -v timeout >/dev/null 2>&1; then TIMEOUT_CMD="timeout 180"
elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_CMD="gtimeout 180"
else TIMEOUT_CMD=""; fi

if [[ "${REVIEW_MODE:-self}" == "spec" ]]; then
  DISPATCH_BASE="${TASK_DIR}"
else
  DISPATCH_BASE="$HOME/.agent/reviews/$REPO/$BRANCH"
fi

mkdir -p "$DISPATCH_BASE/personas"
RUN_DIR="$(mktemp -d "$DISPATCH_BASE/personas/run-XXXXXXXXXX")"
mkdir -p "$RUN_DIR/prompts" "$RUN_DIR/output"

# Write diff/spec content to a shared file so all reviewers can read it
SOURCE_FILE="$RUN_DIR/source.txt"
if [[ -n "${DIFF_CONTENT:-}" ]]; then
  printf '%s' "$DIFF_CONTENT" > "$SOURCE_FILE"
elif [[ "${REVIEW_MODE:-self}" == "spec" ]] && [[ -f "${TASK_DIR}/SPEC.md" ]]; then
  cp "$TASK_DIR/SPEC.md" "$SOURCE_FILE"
else
  # Fallback: capture diff to file
  git -C "$REPO_ROOT" diff main...HEAD > "$SOURCE_FILE" 2>/dev/null ||   git -C "$REPO_ROOT" diff HEAD~1 > "$SOURCE_FILE" 2>/dev/null || true
fi

for reviewer in "${REVIEWERS[@]}"; do
  {
    cat "$REPO_ROOT/.cursor/agents/reviewer-${reviewer}.md"
    printf '

---

## Review context

Mode: %s

## Source material

' "${REVIEW_MODE:-self}"
    cat "$SOURCE_FILE"
    printf '

---

Produce your review now. Follow the output format in your persona definition.
'
  } > "$RUN_DIR/prompts/${reviewer}.txt"
done

PIDS=()
for i in "${!REVIEWERS[@]}"; do
  name="${REVIEWERS[$i]}"
  model_flag=""
  for fast in "${FAST_REVIEWERS[@]}"; do
    [[ "$name" == "$fast" ]] && { model_flag="--model $FAST_MODEL"; break; }
  done
  $TIMEOUT_CMD claude -p $model_flag < "$RUN_DIR/prompts/${name}.txt"     > "$RUN_DIR/output/${name}.txt" 2>"$RUN_DIR/output/${name}.stderr" &
  PIDS+=($!)
done

FAILURES=()
for i in "${!REVIEWERS[@]}"; do
  name="${REVIEWERS[$i]}"
  if ! wait "${PIDS[$i]}"; then FAILURES+=("$name (exit $?)")
  elif [[ ! -s "$RUN_DIR/output/${name}.txt" ]]; then FAILURES+=("$name (empty output)"); fi
done

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  printf 'dispatch-reviewers: failures: %s\n' "${FAILURES[@]}" >&2
  exit 1
fi

# Print results to stdout for the caller to consolidate
for reviewer in "${REVIEWERS[@]}"; do
  echo "=== $reviewer ==="
  cat "$RUN_DIR/output/${reviewer}.txt"
  echo ""
done
