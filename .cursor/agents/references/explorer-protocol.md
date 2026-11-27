# Explorer protocol

How the read-only explorers (`specwriter-explorer`, `reviewer-explorer`) search. Each explorer file
sets its own questions, budget counts, and output sections; this file sets how the calls are spent.

## Tool priority

Lookups: follow `~/.cursor/agents/references/lookups.md` before you search for code whose file you do not already know, or rely on a product or API fact.
Follow `crew-explorer-conventions.mdc` too when it is loaded. Read only the ranges a search
identified, never a whole file: the summary you return is what the consumer reads instead of the
file.

## Budget slots

The explorer's budget line gives a count per slot and a total; stop when the total is spent and report
what is still open.

| Slot | Calls that count |
| --- | --- |
| protocol read | reading this file, once, before any other call |
| lookups read | reading `lookups.md`, once, right after the protocol read |
| docs lookup | a docs-server search or page fetch, or an official-docs or library-source read, for a product or API fact a question depends on |
| index check | the index's repository or ref list, once, before any index search |
| index search | the index's search, grep or tree tool, or the harness's own index search |
| repository search | a path or text search (`Grep`/`Glob` in Cursor, the native search tool elsewhere) |
| file read | the index's line-range read, or a native read of a line range |

When the code index is unreachable, the index slots go to repository search, and the lookups line
`code search unreachable: used text search` goes in the summary.

## Returning

Return the structured summary the explorer file defines. Omit a section with nothing in it rather
than padding it; keep excerpts to the lines that show the pattern; never paste a whole file. The
summary feeds directly into the consumer's context, so a fact you already summarized is one the
consumer does not re-read.
