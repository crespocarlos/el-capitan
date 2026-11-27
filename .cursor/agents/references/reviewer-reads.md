## Finding things in the codebase

Lookups: follow `~/.cursor/agents/references/lookups.md` before you search for code whose file you do not already know, or rely on a product or API fact.
Your package appends that file after this contract, so following it costs no read. When it sends you
to text search, put `code search unreachable: used text search` on its own line directly after the
`Assessment:` line.

**Look beyond the package, briefly.** A package shows the change, not what depends on it, and an
explorer section reaches only some packages. Spend at least one call, and at most a third of your
budget, on what the change touches: a caller or consumer before any compatibility or blast-radius
claim, the tests of the changed code, or sibling code before any reuse claim. Searches your persona's
procedure or attacks require come first and may exceed that cap; it applies to discretionary reads.
Put
`Read beyond the package: <files, or none>` on its own line directly after the `Assessment:` line
(after the code-search note when there is one), so the reader can tell what the review saw.

**Tool-call budget: the number your persona file gives** ("stop calling tools at N", its
`tool_budget` frontmatter), counting text search, read, index search, and docs lookup together.
Count before each call, and stop at N and write the review.
