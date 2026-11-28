---
name: crew-memory
disable-model-invocation: true
description: "Add a durable lesson to memory, draft candidates from the journal, consolidate the inbox, or import legacy journals. Triggers: 'crew memory add <text>' and 'crew memory seed|consolidate|journal'."
---

# Memory

Follow `~/.cursor/skills/crew-memory/references/contract.md`.

## Add

`crew memory add <text>`: validate the candidate against the write gate. For an approved candidate, run `crew-tool.py mem-write TYPE SCOPE TITLE BODY`
with a typed scope and title and the claim as BODY. On exit 3, show the duplicate ids and ask
whether to supersede or skip. On exit 2, print `warning: memory unavailable`.

## Journal, seed, consolidate

`crew memory journal [import] [--dry-run]` (bare `journal` means `import`) runs `crew-mem.py journal
import`, which imports legacy `~/.agent/journal` files as immutable observations without editing
them; on exit 2 print `warning: memory unavailable`. New entries use `crew-mem.py journal add` via `crew
log`. `crew memory seed` follows the seed procedure. `crew memory consolidate` runs `crew-mem.py
consolidate`, which classifies each inbox candidate as `ADD`, `UPDATE`, `SUPERSEDE`, or `NOOP`;
present those actions and wait for explicit approval before changing memory.
