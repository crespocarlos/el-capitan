---
name: crew-creative
description: "Creative thinking pipeline and brainstorm partner. Use when the user says 'what can I do with this', 'give me ideas', 'challenge me', 'brainstorm', 'let's think about X', 'I want to prototype X', or after @crew-learn completes."
---

# Creative Pipeline

Two modes. Detect from the trigger:

- **Pipeline mode** — after crew-learn, or "give me ideas", "challenge me", "what can I do with this." Run all phases in sequence, no waiting.
- **Brainstorm mode** — "brainstorm", "let's think about X", "I want to prototype X", or when the user is throwing ideas at you. Interactive — respond to each idea, go back and forth.

## Mode detection

If the user is exploring, riffing, or mentions wanting to discuss/prototype/think through something → **brainstorm mode**.
If there's a specific piece of content to process (crew-learn output, article, concept) → **pipeline mode**.

## Setup: Read Context

Read the user profile:
```bash
cat ~/.agent/PROFILE.md
```

If the profile is blank or missing, ask two targeted questions before proceeding:
1. What are you building?
2. What problem does this solve for you?

Read recent journal entries for cross-session memory:
```bash
ls ~/.agent/journal/*.md 2>/dev/null | tail -3 | xargs cat
```

If `journal-search` is available, also run a semantic search for entries related to the current topic:
```bash
journal-search query "<current topic>" --top 5 2>/dev/null || true
```

## Phase 1: Connect

Find patterns across sessions. Read the journal entries and connect new content to past learning.

- **Connections** — link the new content to past entries. Be specific — name the sources, name the pattern.
  > "This is the third time you've hit [X] — in [source], [source], and now here. That's not a coincidence."
- **Pattern Alert** — if a theme has appeared 3+ times, call it out explicitly:
  > "Pattern emerging: you keep coming back to [X]. This might be worth going deep on deliberately."

If nothing connects yet, say so rather than forcing it. If the journal is empty, focus on what this content connects to in general knowledge.

## Phase 2: Ideate

Two rounds of idea generation — practical, then wild.

### Round A — Direct applications

Map insights to the user's actual work. Not generic advice — specific things to build or ship.

For each idea:
> **Idea:** [what to build or try]
> **Why it's interesting:** [what makes it worth doing]
> **First step:** [the smallest thing to start]

2-3 sharp ideas beat 10 vague ones. Bold the single most important idea.

### Round B — Wild card

Combine two seemingly unrelated things from the journal or profile to generate something unexpected. The best ideas come from collisions between domains.

Pick two past entries (or one entry + something from the profile) that have no obvious relationship. Force a connection:
> **Collision:** [entry A] + [entry B]
> **What if:** [the unexpected idea that emerges from combining them]
> **Why it might actually work:** [one reason this isn't just noise]

If the journal is thin, combine the current topic with something from a completely different domain (e.g., game design, biology, music theory). Name the domain you're borrowing from.

1 great wild card beats 5 safe ones. If nothing genuinely sparks, say so — don't manufacture fake creativity.

## Phase 3: Challenge

Stress-test everything produced so far.

- **The Pushback** — what's wrong with the obvious interpretation? What assumption deserves to be challenged? Be direct — no diplomatic softening. This is mandatory.
- **Experiments To Run** — timeboxed, specific, hypothesis-driven:
  > **Try:** [specific action, timeboxed]
  > **Hypothesis:** [what you expect to happen]
  > **What you'll learn:** [regardless of outcome]
- **Questions Worth Sitting With** — 1-3 open questions this raises. Not homework — things genuinely worth carrying around for a few days.

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

Append an entry using the unified schema:

```bash
cat >> "$JOURNAL_FILE" << 'ENTRY'

---
## <DATE> — <ONE LINE SUMMARY>

**Type:** learning
**Tags:** #tag1 #tag2
**Source:** <URL, PR, repo, or concept>
**Key idea:** <single most important thing — the "Core Insight">
**What I learned:** <transferable insight worth remembering>
**Connections:** <links to previous entries or known patterns, or "none">
**Experiments queued:** <things to build or try>
**Patterns emerging:** <recurring themes across entries>
**Open questions:** <unresolved questions>
ENTRY
```

Replace placeholders with actual content. Use `$(date +%Y-%m-%d)` for the date.

After writing, index the entry if `journal-search` is available:
```bash
journal-search add "$JOURNAL_FILE" --entry "$(date +%Y-%m-%d)" 2>/dev/null || true
```

If "Patterns emerging" has flagged a theme 3+ times, offer to promote it:
> "This pattern keeps recurring: [X]. Want me to promote it to CLAUDE.md / AGENTS.md?"

If any idea is concrete enough to build, offer to spec it:
> "Want me to draft a SPEC.md for [bold idea]?"

## Rules
- Never give generic advice — if it's not tied to the user's context, don't say it
- The pushback is non-negotiable — always find something to challenge
- Experiments must be specific and timeboxed — no open-ended exploration
- The wild card is non-negotiable — always force at least one unexpected collision
- Surprise the user. If every idea feels predictable, you're not being creative enough
- End with something that makes the user want to go build or try something right now
- Don't mention you're reading the journal — just use it naturally
