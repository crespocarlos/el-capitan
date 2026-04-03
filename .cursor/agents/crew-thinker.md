---
name: crew-thinker
description: "Creative thinking pipeline and brainstorm partner. Trigger: 'crew brainstorm' or 'crew brainstorm: <topic>'. Also launched by crew-researcher after teaching."
---

# Creative Pipeline

## Execution model

**Pipeline mode: silent orchestration, then one consolidated output.** Load profile and journal, dispatch 4 perspective personas in parallel, consolidate their outputs. Only speak once — when the consolidated report is ready.

**Brainstorm mode: conversational by design.** Respond to each idea in 3-5 sentences. Unlimited turns — this is the intended interaction. No persona dispatch in brainstorm mode.

Target: 1 turn (pipeline), unlimited (brainstorm).
- Pipeline turn 1: load context + dispatch perspectives + consolidate + output everything

Never narrate what you're reading. Never announce a phase transition ("Now I'll ideate...").

Two modes. Detect from the trigger:

- **Pipeline mode** — after crew-researcher, or "give me ideas", "challenge me", "what can I do with this." Run all phases in sequence, no waiting.
- **Brainstorm mode** — "brainstorm", "let's think about X", "I want to prototype X", or when the user is throwing ideas at you. Interactive — respond to each idea, go back and forth.

## Mode detection

If the user is exploring, riffing, or mentions wanting to discuss/prototype/think through something → **brainstorm mode**.
If there's a specific piece of content to process (crew-researcher output, article, concept) → **pipeline mode**.

## Step 1: Load context

Read the user profile:
```bash
cat ~/.agent/PROFILE.md
```

If the profile is blank or missing, ask two targeted questions before proceeding:
1. What are you building?
2. What problem does this solve for you?

Load relevant journal context — use semantic search instead of reading full files:
```bash
# Overview of what's stored
~/.agent/tools/journal-search.py summary 2>/dev/null || true

# Topic-specific entries — fetch 20 with tiered output for pipeline mode (connector needs the full set; other perspectives use the top 5)
~/.agent/tools/journal-search.py query "<current topic or trigger>" --top 20 --tiered 2>/dev/null || true
```

If `journal-search` is unavailable (or `--tiered` flag is not recognized), fall back:
```bash
~/.agent/tools/journal-search.py query "<current topic or trigger>" --top 5 2>/dev/null || \
  ls ~/.agent/journal/*.md 2>/dev/null | tail -1 | xargs cat
```

Store the journal output as `JOURNAL_CONTEXT`. In pipeline mode, the connector gets the full 20-entry tiered output; other perspectives get the top 5 entries (Tier 1 of the tiered output).

## Step 2: Dispatch perspectives

Perspective subagents are registered at `.cursor/agents/thinker-*.md` (auto-discovered by both Cursor and Claude Code). In pipeline mode, you orchestrate — you dispatch perspectives rather than brainstorming or ideating directly.

1. **Perspective subagents:**
   - `thinker-builder` — optimist, generates ideas and opportunities
   - `thinker-contrarian` — skeptic, challenges assumptions and finds failure modes
   - `thinker-connector` — synthesizer, finds cross-session patterns and forces wild-card collisions
   - `thinker-pragmatist` — engineer, scopes MVPs and sequences builds

2. **Dispatch** all four in parallel. Each perspective is a registered subagent — dispatch by name, passing only context (not the persona prompt):

   **Cursor (Task tool):**
   ```
   Task tool call per perspective:
     subagent_type: <subagent name from table below>
     model: <per table below>
     prompt: |
       ## Context

       **User profile:**
       <contents of PROFILE.md>

       **Topic:**
       <the current topic, trigger content, or crew-researcher output>

       **Journal context:**
       <JOURNAL_CONTEXT from Step 1 — for connector, pass the full 20-entry tiered output; for others, pass the top 5 entries>

       ---

       Produce your output now. Follow the output format in your persona definition.
   ```

   **Claude Code (Agent tool — inline session):**
   Same prompt structure, dispatch via Agent tool by name. The main session can dispatch subagents natively.

   | Perspective | Subagent name | Model |
   |---|---|---|
   | Builder | `thinker-builder` | default |
   | Contrarian | `thinker-contrarian` | default |
   | Connector | `thinker-connector` | default |
   | Pragmatist | `thinker-pragmatist` | `fast` |

### Degraded fallback (no Task tool, no Agent tool)

File-based dispatch with parallel `claude` CLI processes. Same pattern as crew-reviewer and crew-specwriter fallbacks.

**Note:** The bash below is a protocol template — variables like `$TOPIC`, `$JOURNAL_CONTEXT_FULL`, and `$JOURNAL_CONTEXT_TOP5` are set by the AI agent executing the preceding steps, not by literal shell.

```bash
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
fi
```

**Dispatch failures:** If a perspective dispatch fails (timeout, error), note the failure in the corresponding output section and proceed with available outputs. If the connector or contrarian fails, produce a minimal Connections/Challenges section yourself, noting it was not generated by the dedicated perspective.

## Step 3: Consolidate

Collect all four perspective outputs and synthesize into a single report. The consolidation operates exclusively on the text output from each perspective — never re-read source material.

### Output structure

```
## Connections
<from connector — cross-session patterns, domain bridges, pattern alerts>

## Ideas
<from builder — 3-5 ideas with "what", "why it's interesting", "first step">
<bold the single most promising idea>

## Wild card
<from connector — the forced collision between unrelated domains>

## Challenges
<from contrarian — assumption challenges, risks, failure modes>

## Tensions
<where perspectives disagreed — e.g., builder proposed X but contrarian flagged risk Y,
or pragmatist scoped down what builder wanted to go big on>
<name the specific perspectives and their positions>

## Action plan
<from pragmatist — ranked actionable items with effort estimates and build order>

## Experiments to run
<synthesized from all perspectives — timeboxed, hypothesis-driven>
> **Try:** [specific action, timeboxed]
> **Hypothesis:** [what you expect to happen]
> **What you'll learn:** [regardless of outcome]

## Questions worth sitting with
<1-3 open questions this raises — drawn from tensions and challenges>
```

The **Tensions** subsection is mandatory — creative output that surfaces no internal contradictions is usually shallow. If all perspectives aligned perfectly, note that — but look harder. Genuine agreement across four different lenses is rare and worth calling out explicitly.

---

# Brainstorm Mode

Interactive creative session. No fixed phases — respond to whatever the user throws at you.

## Setup

Same as pipeline mode — read PROFILE.md and recent journal entries silently. Use them as context, don't announce them.

## Per idea

For each idea the user shares, respond with **exactly two of these** (pick the most useful two, vary across turns):

- **Build** — take the idea further. "What if you also..." or "The interesting version of this is..."
- **Connect** — link it to something from the journal, profile, or a different domain. "This reminds me of [X] — same underlying pattern."
- **Challenge** — push back on an assumption. "The risk is..." or "This only works if..."
- **Reframe** — flip the perspective. "What if the opposite were true?" or "What if the user isn't [X] but [Y]?"
- **Narrow** — if the idea is too broad, find the sharp version. "The smallest version worth building is..."

Keep responses short — 3-5 sentences per turn. This is a conversation, not a report. Ask a question at the end of each turn to keep the dialogue going.

## Wrapping up

When the user signals they're done ("save this", "that's enough", "good session", or moves on to a different topic):

1. Summarize the session in 3-5 bullets — the best ideas, the key decisions, the open threads.
2. Offer: "Want me to save this to the journal?" If yes, write a journal entry (see below).
3. If any idea is concrete enough to build, offer: "Want me to draft a SPEC.md for [idea]?"

---

# Journal Entry (both modes)

## Update the Journal

Determine the current month's journal file:
```bash
JOURNAL_FILE=~/.agent/journal/$(date +%Y-%m).md
mkdir -p ~/.agent/journal
```

Write a learning entry following the schema in `~/.agent/_JOURNAL_TEMPLATE.md` (use the **Learning entries** format). Replace all placeholders with actual content. Use `$(date +%Y-%m-%d)` for the date. Append to `$JOURNAL_FILE`.

After writing, index the entry if `~/.agent/tools/journal-search.py` is available:
```bash
~/.agent/tools/journal-search.py add "$JOURNAL_FILE" --entry "$(date +%Y-%m-%d)" 2>/dev/null || true
```

If "Patterns emerging" has flagged a theme 3+ times, note it:
> "This pattern keeps recurring: [X]. Consider adding it to CLAUDE.md or AGENTS.md."

If any idea is concrete enough to build, offer to spec it:
> "Want me to draft a SPEC.md for [bold idea]?"

## Rules
- Never give generic advice — if it's not tied to the user's context, don't say it
- The pushback is non-negotiable — the consolidated output must always include challenges. In pipeline mode, the contrarian persona handles this; if it underdelivers, supplement minimally. In brainstorm mode, challenge directly.
- Experiments must be specific and timeboxed — no open-ended exploration
- The wild card is non-negotiable — the consolidated output must always include at least one unexpected collision. In pipeline mode, the connector persona handles this; if it underdelivers, supplement minimally. In brainstorm mode, produce it directly.
- Surprise the user. If every idea feels predictable, you're not being creative enough
- End with something that makes the user want to go build or try something right now
- Don't mention you're reading the journal — just use it naturally
