# Explorer protocol

How the read-only explorers (`specwriter-explorer`, `reviewer-explorer`) search. Each explorer file
sets its own questions, budget counts, and output sections; this file sets how the calls are spent.

## Tool priority

Follow `crew-explorer-conventions.mdc` when it is loaded. Either way, prefer a code index
(Sourcerer's, when configured) over a text search; otherwise use the native search tool, then read
only the ranges a search identified. Never read a whole file: the summary you return is what the
consumer reads instead of the file.

## Budget slots

The explorer's budget line gives a count per slot and a total; stop when the total is spent and report
what is still open.

| Slot | Calls that count |
| --- | --- |
| protocol read | reading this file, once, before any other call |
| index check | `sourcerer_repos_list` or `sourcerer_refs_list`, once, before any index search |
| index search | `sourcerer_code_search`, `sourcerer_code_grep`, `sourcerer_files_tree`, or the harness's own index search |
| repository search | a path or text search (`Grep`/`Glob` in Cursor, the native search tool elsewhere) |
| file read | `sourcerer_files_read_lines`, or a native read of a line range |

When the code index is unreachable (not in your tools, or a call fails), the index slots go to
repository search; name it in the summary as `code search unreachable: used text search`, so the
consumer knows the results were not ranked.

## Returning

Return the structured summary the explorer file defines. Omit a section with nothing in it rather
than padding it; keep excerpts to the lines that show the pattern; never paste a whole file. The
summary feeds directly into the consumer's context, so a fact you already summarized is one the
consumer does not re-read.
