# Shared reviewer contract

Your persona file sets your lens; this file sets your output. Where they disagree about output, this
file wins: `review-findings.py` and `consolidation.md` parse the format defined here.

## Labels

Exactly one label per finding, from this closed set; any other label fails normalization.

| Label | Use it for |
| --- | --- |
| `[blocking]` | Must resolve before the change proceeds: a broken assumption, a defect that reaches production, a contract that breaks a consumer. |
| `[attention]` | Worth fixing, not required: a real weakness with a clear fix. |
| `[needs more info]` | You cannot judge without an answer. State the stakes: what breaks if the assumption is wrong. |
| `[nit]` | Polish with a stated cost. A nit with no cost is noise — drop it. |
| `[concern]` | Only in a spec or idea review, in place of `[attention]`: the plan or reasoning is weakened, but nothing is implemented yet. `[blocking]` keeps its plan meaning there — a broken assumption or a missing requirement. |

A question without stated stakes is a nit in disguise: upgrade it or drop it. Prefer fewer findings
that name a concrete harm; the reader acts on a short report and skims a long one.

## Finding shape

Each finding is a comment body the reader can paste without editing:
`N. [label] **\`path/to/file — line N\`** — one-line title`, then a 2-5 line fenced block anchoring
the finding, then 2-3 sentences on what is wrong and why it breaks, then `Fix:` (that exact
spelling; the consolidator records it as the `patch` disposition and loses any other).

- Anchor to `path:line`. In a spec or idea review, anchor to the section and quote the sentence.
- With a hunk index in the package, a `[blocking]` or `[attention]` finding also cites the hunk ids
  that cause it, next to the anchor: `[attention] src/a.ts:42 (h7) — …`.
- Quote the wording, line, or behavior verbatim; a paraphrase is an anchor nobody can verify.
- One issue per finding. Split two problems even when they share a root cause, or one fix hides the
  other from every downstream count.
- Say whether the defect pre-exists: if its cause is in code or text the change does not touch, say
  so; a finding whose claimed cause is not in the diff is pre-existing by definition. Consolidation
  routes pre-existing problems to a deferred list instead of blocking on them.

## When you have nothing

A complete review with nothing in your lane ends with exactly these two lines, then one sentence
naming what the artifact lacks:

```
Nothing in my lane for this artifact.
### Verdict: no findings
```

A review that examined the artifact and found no defect ends with `### Verdict: no findings` alone.
The verdict line is required: a response with neither a finding nor that line is read as truncated
and relaunched. Zero findings is a valid outcome; never pad, and never report a finding you could
not ground.

## Evidence rules

- Ground every claim in the artifact or the package. If it needs a read you cannot make, mark it
  `[needs more info]` and name the blocked read.
- An absence claim ("nothing validates this") requires reading the code that would hold it; absence
  from a diff is not absence from the file.
- Never re-read a file the package contains, and never read a whole file to answer a `path:line`
  question.
- Stay inside your lens. A problem that belongs to another lens costs a consolidation slot and hides
  the finding that would have covered it properly.

## Finding things in the codebase

Semantic search first: it finds code by meaning; a text search finds only the string you guessed.
Take the first row that fits and stop there:

| Task | Use |
| --- | --- |
| Where does this concept live? | `discover_directories`, then `map_symbols_by_query` |
| Find a symbol, or every file using known symbols | `map_symbols_by_query`, or `symbol_analysis` |
| Natural-language query, no symbol or directory known | `semantic_code_search` |
| Definition, call sites, types, tests of one symbol | `symbol_analysis` |
| Outline of one known file | `document_symbols` |
| Read a file that search identified | `read_file_from_chunks` |
| Verify one exact string in a located file | a text search (`Grep`) |
| Find files by path once you know the area | a path search (`Glob`) |
| Which repos are indexed, or results look wrong | `list_indices` |
| The server rejects a call | `auth_status`, then retry once |

These are the semantic code search server's ids (`mcp__semantic-code-search__*`) plus the native
`Grep` and `Glob`; in a harness with different names, use its equivalents in the same order. Never
start with a text search while exploring; it is correct once search has narrowed the scope, or when
the finding already names its file and line. Read a whole file only as a last resort.
`~/.cursor/rules/crew-explorer-conventions.mdc` has the KQL syntax for `map_symbols_by_query`.

**Tool-call budget: ≤8 file-fetch calls** (text search, read, and semantic search combined). Fetch
only when a finding cannot be grounded from the artifact and package; count before each call and
stop at 8.

## Elastic docs claims

Verify ES|QL (`.esql` files, `FROM … |`, `esql` identifiers) and Elasticsearch or Kibana API claims
against the docs server, never from memory: search with `search_internal_docs`, confirm with
`get_internal_document_by_url`, cite the URL. The semantic index shows how code builds a query, not
whether the syntax is valid. With no docs server, or a failed lookup, mark the claim `unverified`: a
guessed option is indistinguishable from a verified one.
