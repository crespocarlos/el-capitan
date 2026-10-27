# Journal Entry Schema

New entries are stored as immutable observations by `mem.py journal add` (see `crew-log`) under `~/.agent/memory/observations/`. The format below is the legacy monthly-file layout in `~/.agent/journal/YYYY-MM.md`, which is import-only (`mem.py journal import`).

## Format

```markdown
---

## YYYY-MM-DD — Title (one line, what this entry is about)

**Tags:** #tag1 #tag2
**Repo:** repo-name  (omit if not repo-scoped)

One or more paragraphs. Each paragraph is one coherent idea — write it with enough
context to be useful as evidence months later. Include the "why": not just what
happened, but why it matters and when it applies again.

Separate distinct ideas with a blank line. Journal entries are evidence, not
retrieved memory units. A later `crew memory seed` or completion workflow may draft
an approval-gated typed memory candidate that points back to this entry.

---
```

## What makes a good entry

**Self-contained paragraphs.** A candidate may cite one paragraph as its evidence, so
each paragraph should make sense on its own. Don't write "as mentioned above" or rely
on surrounding context.

**Write the why.** "Always bump the data stream version when adding mapping fields"
is less useful than "When adding new mapping fields to a Kibana data stream, bump the
version or the fields won't be mapped on existing deployments — the install path in
@kbn/data-streams gates entirely on the version field, so fresh installs work fine
which makes this easy to miss in dev."

**One idea per paragraph.** Don't pack unrelated observations into one block. A
5-paragraph entry with 5 distinct insights is more retrievable than a single dense
paragraph covering everything.

## Tags

Use `**Tags:**` for topic keywords (`#sigevents`, `#el-capitan`, `#mapping`).
Use `**Repo:**` for repo scoping — entries without it are global.

No other metadata fields are required. Don't add Type, Source, Key idea, Experiments,
Patterns emerging, etc. — those fields generated noise and placeholder text.

## Examples

```markdown
---

## 2026-05-30 — Kibana data stream version gating

When adding new mapping fields to a Kibana data stream, the version number must be
bumped or the new fields won't be mapped on existing deployments. The install path in
@kbn/data-streams gates entirely on the version field — fresh installs work fine
which makes this easy to miss in dev. Applied to detections (3→4), discoveries (2→3),
events (3→4) in the streams plugin.

**Tags:** #kibana #streams #mapping
**Repo:** kibana

---

## 2026-05-30 — Zod strips unknown keys by default

Zod strips unknown keys from objects by default. This means a schema must explicitly
declare every field the write path uses, or those fields get silently dropped before
storage. The failure mode is silent: writes succeed, reads return nothing, no error
anywhere. Caught when discoverySchema declared closes/grouped_into while the mapping
and queries used closes_discovery_id and grouped_discovery_ids — writes through the
route stripped the new field names before they reached ES.

**Tags:** #zod #schema #kibana
**Repo:** kibana

---
```
