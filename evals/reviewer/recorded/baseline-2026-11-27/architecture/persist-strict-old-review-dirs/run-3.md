Assessment: request-changes — the `--strict` gate in `persist` can reject already-written review dirs, and its error message points at a `spec-context` command I can't find in the file.

1. [attention · 3] **`.agent/tools/review-findings.py:60`** — error message names a `spec-context` subcommand that doesn't exist in this file
```
"build its spec with `review-findings.py spec-context`")
```
A grep of the changed file finds `spec-context` only in this string. `spec_sections` is defined but nothing in the file calls it. If the subcommand is not added elsewhere, the gate tells users to run a command that fails. The spec-trimming itself also never reaches the orchestrator, so the check can't be satisfied. I could not see the orchestrator or the CLI parser, so I can't confirm where the producer lives.
Fix: add the `spec-context` subcommand in the same change, built on `spec_sections`, and register it. If it already exists in another file, say so in the message.

2. [attention · 3] **`.agent/tools/review-findings.py:94`** — `--strict` now fails on review dirs written before this change
```
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
Any existing `<persona>.in.md` that embeds `diff.patch` hunks of a generated file, or the full spec, now makes `persist --strict` raise. That applies to in-flight reviews and re-persists of old dirs, and nothing lets a caller bypass it. The `continue` on a missing package covers dirs with no package files, but not old ones that have them. The finding is a rollout risk, not a defect in the check's logic.
Fix: gate the check on a marker that the package was built by the new orchestrator, or add an explicit opt-out flag. At minimum, document that old dirs need regenerating.

3. [attention · 3] **`.agent/tools/review-findings.py:46`** — the copied-spec check is a heuristic coupled to the spec's line format
```
if len(copied) >= 2:
```
The check passes when a package copies fewer than 2 builder lines of 40+ characters. It also misses reformatted or wrapped lines, and it never looks at fenced `## Tasks` headings. The generated-file check likewise matches `line.endswith(" b/<path>")`, so a renamed or quoted path slips through. These are hard-coded text-matching conventions between producer and validator. The blocking `ValueError` is stronger than the evidence supports.
Fix: have the producer write a sidecar or marker line (for example, "spec: trimmed") and validate that. Otherwise downgrade the check to a warning.

4. [needs more info · 2] **`.agent/tools/review-findings.py:51`** — `canonical_personas` and `read_json_object` are not defined in this file
`canonical_personas(personas, split_commas=False)` and `read_json_object(hunks_path, "files")` are only called here. The file I could read has no definitions or imports for them. If they live in an unshown module, the new call signatures (`split_commas`, the `"files"` key) must match it. If they are missing, `persist --strict` raises `NameError`. Can you confirm both exist with these signatures?