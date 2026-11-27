Assessment: request-changes — the size trigger for path delivery can't be evaluated, and the new text conflicts with PR mode's ban on file reads.

1. [blocking · 4] **`.cursor/agents/references/dispatch.md:31`** — PR mode's "no file reads" rule contradicts path delivery

```
**PR mode:** the package is the only repository evidence a persona may use. ...
A persona must not use the local
checkout — no file reads, repository search, semantic search, or Explorer output, whatever the
harness names those tools — to verify a PR claim.
```

Path delivery tells the persona to read `<persona>.in.md` with `Read`. PR mode bans "no file reads" with no exception for the package file. The new section never says whether PR mode applies to it. The most likely large-package case is a PR review, so a model has to reconcile the two rules, and some will refuse to read the package. A persona that obeys PR mode literally reviews nothing. Pre-existing text, but the change creates the collision.
Fix: add an exception to PR mode, for example "except the package file named in the dispatch prompt under **Package delivery**". Also state that path delivery is allowed in PR mode.

2. [attention · 4] **`.cursor/agents/references/dispatch.md:26`** — the size trigger can't be evaluated

```
Use it when embedding would push the orchestrator's own output past what the harness accepts —
one measured five-persona review was 640 KB
```

The heading says "when a package is too large to embed", but no threshold or check is given. The orchestrator can't know what "the harness accepts". The single 640 KB example is a total across five personas, not a per-package size. Orchestrators will pick different cutoffs, and some will use path delivery on small packages. Conditions 1 and 2 are only eligibility checks, not triggers, and nothing stops path delivery being used by default when they hold.
Fix: give an observable criterion, such as a per-package byte limit (for example "a package over N KB, or a combined dispatch over M KB"). Also say that when conditions 1 and 2 hold but the package is small, it is embedded.

3. [attention · 3] **`.cursor/agents/references/dispatch.md:22`** — condition 3 asks for a restatement and adds no fallback

```
repeats only the delivery-independent instructions: reply text only, no artifact writes, the finding shape, and the mode.
```

"The finding shape" and "reply text only" are rules owned by the shared contract. Listing them here makes a second copy that can drift. Also, if the persona's `Read` fails or the file is truncated, there is no fallback. Without one, the persona may review from nothing or invent content.
Fix: replace the list with a pointer, such as "repeats the return-shape and mode lines from the shared contract verbatim". Add "if the file cannot be read in full, reply `status: failed`".

4. [nit · 3] **`.cursor/agents/references/dispatch.md:10`** — "inline" is defined only further down

```
deliver it inline, or by path under **Package delivery** below.
```

The earlier sentence still says an unreadable diff path isn't evidence, and the new section says the same thing again at line 14. This costs a few lines of duplication. It also leaves a reader who stops at line 11 unsure whether a path is acceptable.
Fix: keep the "a path to a diff file on its own is not evidence" rule only in the Package delivery section.