Assessment: request-changes — the new `--strict` gate points at a `spec-context` command that doesn't exist in the code I can see, and it fails old review directories with no way round it.

Read beyond the package: `.agent/tools/review-findings.py` (grep for `spec-context`, `package.diff`, `strict`; read `persist`).

Approach: redirect — Keep the smaller packages. Have the builder enforce the rules, with `persist --strict` as a cheap backstop, instead of re-deriving the rules by line-matching the output.
Alternatives considered:
- Don't build the gate, and only change the orchestrator to embed `package.diff` and a filtered spec. This is the cheapest option and delivers the size saving. It loses the guarantee that a stale package can't reach REVIEW.md. That risk is real but small.
- Put the filter and its check in one function, with the builder writing a manifest (for example `{persona}.in.meta.json` listing the spec sections and diff source used). Strict then validates the manifest. This beats the chosen design because the rule has one owner, and the gate doesn't have to guess from text.
- Chosen design: re-parse the spec in the gate and match its lines against the package text. It works, but it duplicates the split rule and is heuristic.

1. [blocking · 4] **`.agent/tools/review-findings.py:60`** — the gate's remedy names a `spec-context` subcommand that I couldn't find
```
"build its spec with `review-findings.py spec-context`")
```
`spec_sections` is only a helper. A grep of the file for `spec-context` finds only this message, so no subcommand or argparse registration appears. This is an excerpt, so it may live elsewhere. If it doesn't exist, then when strict fails, the operator is told to run a command that doesn't exist. The orchestrator change that builds packages with `package.diff` and the filtered spec is also not in this diff. Nothing visible produces compliant packages, so every strict persist could fail.
Fix: Add the `spec-context` subcommand, which prints the kept lines from `spec_sections`, in the same change as the gate. Alternatively, change the message to name a command that exists.

2. [attention · 4] **`.agent/tools/review-findings.py:94`** — strict now fails every review directory built before this change, with no escape
```
violations = package_violations(args.review_dir, args.personas, args.mode,
...
raise ValueError("; ".join(violations))
```
Take a review directory whose `<persona>.in.md` files embed `diff.patch` or the full spec. Re-running `persist --strict` on it, for example to re-persist after fixing a finding, now raises. Rebuilding the packages would change the evidence the reviewers actually saw, so that isn't a real option. No version marker or opt-out tells old directories from new ones.
Fix: Record a package format version, or a manifest, when the packages are built. Apply the gate only to directories that carry the marker, and skip it for directories without one.

3. [attention · 3] **`.agent/tools/review-findings.py:41`** — the same rule is kept in two places and checked by line matching
```
builder_lines = {line.strip() for line in spec_sections(...)[1]
                 if len(line.strip()) >= SPEC_LINE_MIN ...
copied = ... if len(copied) >= 2
```
The builder and the gate each decide what counts as "Tasks/Hints". Two different inputs make them disagree. A spec with a short Tasks list, under 40 characters per line or only one long line, gets through. A persona that quotes two long task lines in its prompt, or whose context legitimately repeats them in the summary, is wrongly rejected.
Fix: Have the builder write the manifest from alternative 2, and check that.

4. [attention · 3] **`.agent/tools/review-findings.py:41`** — the gate silently skips the spec check when the spec path is missing or a mode isn't covered
```
if mode in CODE_MODES and spec_path and spec_path.is_file():
```
`owner / "SPEC.md"` is derived from `review_dir.parent.parent`, a layout assumption. If the layout differs, `builder_lines` stays empty and the gate passes with no warning. Likewise, `read_json_object(hunks_path, "files")["files"]` may raise `KeyError` on an older `hunks.json` that lacks `files`. That would turn an old directory's strict persist into a crash instead of a clear violation.
Fix: Report "spec not found, Tasks/Hints check skipped" explicitly. Use `.get("files", [])`.