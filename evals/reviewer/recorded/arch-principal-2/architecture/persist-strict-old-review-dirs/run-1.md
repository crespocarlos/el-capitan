Assessment: request-changes — the gate checks for a package shape that nothing in this diff produces, and it makes `--strict` reject review directories that `persist` is documented as re-runnable on.

Read beyond the package: grep of the working tree for `spec-context`, `canonical_personas`, `read_json_object`, `package.diff` and `diff.patch`, plus a full read of `.agent/tools/review-findings.py`.

Approach: redirect — the savings come from changing what the orchestrator embeds, and a post-hoc `--strict` rejection of finished packages is the wrong layer to enforce it.
Alternatives considered:
- Do nothing in `persist`: have the package builder own the filtering (spec-context and package.diff), with a test on the builder's output. This is cheaper and fails at build time, before the personas are dispatched and paid for. It wins. The diff has only the checker and no builder.
- Keep the gate, but make it opt-in or version-aware. The package would record a format version, and the gate would check only packages that declare the new format. This keeps the gate and avoids breaking old directories. It is the minimum fix if the gate stays.
- Chosen approach: re-parse the written `.in.md` files and match lines against the spec. This is a heuristic with two owners of the rule, and it detects the problem only after the persona has run. It loses.

1. [blocking · 4] **`.agent/tools/review-findings.py:94`** — `--strict` now rejects every review directory built before this change
```
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
The module docstring says `persist` "can be re-run on the same directory after a partial failure and produces the same report." Old directories have `<persona>.in.md` files that embed `diff.patch`, including the generated-file hunks, and carry the full spec with its Tasks. Re-running `persist --strict` on one now raises a `ValueError` and writes no REVIEW.md. The failure is not recoverable, because the packages were already sent to the personas and cannot be rebuilt. Nothing records the package format, so the gate cannot tell old packages from broken new ones.
Fix: write a package-format marker (for example in `hunks.json` or a manifest) when the package is built. Apply `package_violations` only to directories that declare the new format, and leave older ones on the existing gates.

2. [attention · 4] **`.agent/tools/review-findings.py:60`** — the error message points to a command this change does not add
```
"build its spec with `review-findings.py spec-context`")
```
Grep finds `spec-context` only in this string. The diff adds `spec_sections` but no subcommand, no argparse wiring and no code that writes `package.diff`. The change's description says the orchestrator now embeds `package.diff` and strips Tasks/Hints, but no such code is in this diff. A user who hits the violation is told to run a command that does not exist. If the producer lives elsewhere, the splitting rule has two owners: `spec_sections` here and whatever the orchestrator does.
Fix: add `spec-context` and `package.diff` generation in the same change, both using `spec_sections`. Add a test that the builder's output passes `package_violations`.

3. [attention · 3] **`.agent/tools/review-findings.py:57`** — a diff that touches the spec's own Tasks section is flagged as a violation
```
copied = builder_lines.intersection(line.strip() for line in lines)
if len(copied) >= 2:
```
`line.strip()` removes the leading space of a unified-diff context line. When a self or changes review modifies `SPEC.md` near its Tasks, two or more unchanged Tasks lines appear in the embedded diff and match. The gate then rejects a correctly built package, and the strict persist fails for a legitimate reason.
Fix: skip the matching for lines inside `diff --git` blocks whose path is the spec. Alternatively, compare against the persona's spec block only, by delimiting the block in the package.

4. [nit · 3] **`.agent/tools/review-findings.py:49`** — unguarded `["files"]` and `["path"]` access on `hunks.json`
`read_json_object(hunks_path, "files")["files"]` raises a `KeyError` or a `ValueError` on an old or partial `hunks.json`. The gate then fails with a stack trace instead of a message naming the file, which makes recovery harder.
Fix: catch the error and report it as a violation naming `hunks.json`.

Also, `canonical_personas`, `read_json_object`, `read_findings`, `write_review`, `check_hunk_refs` and `hunk_ids` are not defined or imported in this excerpt. I treated them as defined elsewhere, and I could not check that they exist.