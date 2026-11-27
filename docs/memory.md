# Memory

`crew-mem.py` keeps typed Markdown units under `~/.agent/memory` and uses SQLite FTS5 only as a
rebuildable search index. The store is scoped by the upstream repository's bare name, so a fork and
its worktrees share one scope. Code, docs, and your instructions win over anything recalled from it.

## Setup

`bash install.sh` creates the store, installs the `crew-mem.py` command, and adds read instructions
for Cursor, Claude Code, and Codex. After that no routine setup is needed: agents retrieve relevant
memory at task start through `crew-mem.py search` and `context`; it is never loaded wholesale into
every prompt.

## Writing memory

- `crew memory add <lesson>` records one durable fact that is not derivable from code or project
  rules. It checks the write gate and asks before adding a near-duplicate.
- `crew memory seed` drafts approval-gated candidates from the journal.
- `crew memory consolidate` classifies each inbox candidate as `ADD`, `UPDATE`, `SUPERSEDE`, or
  `NOOP` and waits for your approval before changing anything.
- `crew memory journal` imports legacy `~/.agent/journal` files as observations (run
  `crew-mem.py journal import --dry-run` first to see what it takes).

Implementation completion, review-address completion, and `crew log` draft up to three
evidence-backed candidates into the inbox automatically. Lightweight session telemetry records only
tool categories and outcomes; after substantive work or repeated failures, the stop hook asks for
one user-approved candidate review. Candidates are never imported automatically: review the batch
and approve it with `crew memory seed` or `crew-mem.py import-inbox <file> ...`. A bare
`import-inbox` refuses, because the inbox may hold drafts from earlier sessions; `--all` takes the
whole inbox deliberately.

## Observations

The same store holds immutable journal observations. They are indexed as evidence and included in
`search` and ranked `context` retrieval; the `--mode session` listing leaves them out unless
`--include-observations` is passed.

## Moving memory to another machine

`crew-mem.py export <file.tar.gz>` writes every unit and observation to a new archive only you can
read, without the index, the inbox drafts, the session telemetry or the owner's name. It refuses a
target that exists (a link included), and skips, naming each, a link, a hidden file or a unit import
would refuse. On the other machine, after `bash install.sh`, `crew-mem.py import <file.tar.gz>` adds
the units and rebuilds the index; `--dry-run` reports what it would add.

Import never overwrites: a unit that already exists with other text is kept, named on stderr, and the
command exits 1. It checks every member before it writes any, and refuses the whole archive (exit 2)
on a path outside the unit layout, a member over 256 KiB or too many or too large members in all,
bad frontmatter, an unknown type or status, a declared scope other than the one its path implies,
two names that differ only by case, or an id already stored under another path. A write that fails
partway is undone.

The store is also a git repository, so `git` can carry its history if you prefer; export and import
move only the units and merge into a store that already exists.

## Verifying

`python3 evals/memory/run.py` runs the memory evaluation, and `bash evals/test.sh
evals/tools/test_memory.py` the hook, inbox and command tests.
