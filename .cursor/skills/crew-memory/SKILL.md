---
disable-model-invocation: true
name: crew-memory
description: "Manage durable typed memory. Triggers: 'crew remember: <text>' and 'crew memory seed|consolidate|doctor'."
---

# Memory

Follow `~/.cursor/skills/crew-memory/references/contract.md`.

## Remember

Validate the candidate against the write gate. For an approved candidate, run `mem.py add` with a typed scope and title, reading its claim from stdin. On exit 3, show the duplicate ids and ask whether to supersede, force-add, or skip. On exit 2, print `warning: memory unavailable`.

## Seed, consolidate, doctor

`crew memory seed` follows the seed procedure. `crew memory consolidate` runs `mem.py consolidate`; `crew memory doctor` runs `mem.py doctor`.
