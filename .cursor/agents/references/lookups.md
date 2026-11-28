# Lookups

How an agent finds code whose file it does not already know, and checks a product or API fact. Your
own file still sets your budget, your tools and where a note goes in your output; this file sets
which lookup to make and what to do when it cannot be made.

The servers are those in `~/.agent/config.json` `mcp`: `code_search` for the code index,
`docs` for the docs server. Install adds them to each read-only agent's `tools:` line. A read-only agent
calls only these servers; in Cursor, which offers every session server, this line is the only limit; for
anything else use Grep, Glob or Read. An agent with full tool access may call any server the session
has. Tool names below are the ids of the servers this
file was written against (Sourcerer for code search), given as examples and reached as
`mcp__<server>__<id>`. With other servers, match by function, not name, and keep the same order.

## Notes in your output

Each lookup that cannot be made leaves a one-line note: the code-search line below, or a docs mark on
the claim it concerns. Your own file says where notes go. Without such a place, put them at the end
of your output, before any line your file requires to come last.

## Code whose file you do not know

Search the code index before a text search: it ranks by relevance across whole repositories. Take the
first row that fits and stop there. When you already know the file and line, read it directly; the index is for discovery.

| Task | Use |
| --- | --- |
| Where does this concept live? | `sourcerer_code_search` with a described query, then `sourcerer_files_tree` on the directory it names |
| Find code by identifier, error text, or config key | `sourcerer_code_grep` (exact regex) |
| Outline of one known directory | `sourcerer_files_tree` |
| Read a file search identified, or a line range | `sourcerer_files_read_lines` |
| Read a whole file | `sourcerer_files_cat` |
| Which repositories hold this code | `sourcerer_repos_search`, or `sourcerer_repos_list` |
| Which branch or tag is indexed | `sourcerer_refs_list`; a stale index is the usual reason results look wrong |
| Repository or module orientation prose | `sourcerer_ki_search` |
| Verify one exact string in a file you already located | a text search (`Grep`) |
| Find files by path once you know the area | a path search (`Glob`) |

The index is lexical ranking, not embedding search, so query with the words the code contains. It
holds snapshots of refs: for a version-specific claim pass the branch as `git_ref` and check its
`status` in the ref list (`complete` is safe, `indexing` may be partial, `stale` is not). Read a whole
file only as a last resort.

When the index is not in your tools, or a call fails, use the equivalent `Grep`/`Glob`/`Read` call and
note `code search unreachable: used text search`, so the reader knows the results were not ranked.

## Product and API facts

A claim about how a product, library, API, query language or configuration behaves, when your work
depends on it, is checked and cited, never settled from memory. How this repository's own code
behaves is a code question instead: read the code.

- **A product the docs server covers** (its tool descriptions name what it holds): search it
  (`search_internal_docs` in the example), fetch the page you cite (`get_internal_document_by_url`),
  and cite the URL. The code index shows how code builds a query or calls an API, not whether the
  syntax or the option is valid.
- **Anything else:** check the official documentation or the library's source, and cite the URL or
  the `path:line`.

When the check cannot be made, mark the claim with the reason:

- `unverified (docs server unreachable)`: the claim belongs to the docs server, and it is not in your
  tools or a call failed.
- `unverified (no relevant page)`: the search ran, and neither it nor the official documentation or
  source held the answer.

What follows the mark depends on your role. A reviewer or critic leaves the claim unsettled and
puts the mark in the finding that depends on it. An agent that writes code or a spec proceeds on the
best-supported reading and records the claim with its mark where its file collects claims it could not check.
