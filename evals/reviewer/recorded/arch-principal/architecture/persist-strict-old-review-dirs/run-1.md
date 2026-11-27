Assessment: request-changes — the new `--strict` gate rejects review directories whose `.in.md` files were built the old way, and it names a `spec-context` subcommand that this file does not define.

Read beyond the package: `.agent/tools/review-findings.py` (the `persist` caller), plus a grep of the working directory for `spec-context`, `package_violations`, `--strict` and `canonical_personas`.

Approach: redirect — Enforcing package rules at persist time is the wrong place. Build the package correctly, and have the gate check the builder's output instead of grepping for copied lines.
Alternatives considered:
- Don't gate; have the orchestrator build the package through a single function — this removes the second copy of the section rules and avoids the heuristic. The gate becomes redundant.
- A marker or manifest written by the package builder (for example a `package.json` recording which spec and diff variant was used) that persist validates — it is deterministic and avoids matching on line text. It wins over the 40-character, two-line heuristic.
- The chosen approach, a post-hoc textual check at persist — it is cheap and catches regressions, but it duplicates the section parsing and relies on a fuzzy heuristic.

1. [blocking · 4] **`.agent/tools/review-findings.py:60`** — the error message points to a `spec-context` subcommand that does not exist
```
"build its spec with `review-findings.py spec-context`")
```
A grep of the working directory finds `spec-context` only in this error string. `spec_sections` is defined but nothing exposes it. An operator who hits the violation cannot follow the instruction, and the orchestrator has no way to build the trimmed spec. The change's stated purpose, giving each persona a smaller spec, is therefore not delivered by this tool. The gate can only reject packages. Nothing here can produce a package that passes it.
Fix: add a `spec-context --persona X` subcommand that calls `spec_sections` and prints the trimmed spec. Alternatively, change the message to name the entry point that does exist.

2. [attention · 4] **`.agent/tools/review-findings.py:94`** — the new strict gate fails on review directories built before this change
```
violations = package_violations(args.review_dir, ...)
if violations:
    raise ValueError("; ".join(violations))
```
Take a directory whose `.in.md` files embed `diff.patch` hunks of a generated file, or the full spec. Re-running `persist --strict` on it now raises ValueError, and no REVIEW.md is written. The only escape is to edit the packages by hand, which falsifies the evidence of what the personas saw. There is also no non-strict flag that skips just this gate.
Fix: gate only on a package-format marker recorded at build time. Alternatively, add a `--no-package-check` escape and warn instead of raising for packages that predate the change.

3. [attention · 3] **`.agent/tools/review-findings.py:57`** — the Tasks/Hints detection is a fuzzy heuristic that can miss or misfire
```
copied = builder_lines.intersection(line.strip() for line in lines)
if len(copied) >= 2:
```
A trimmed package that merely quotes two long task lines will be rejected. This is plausible for Product Flow-adjacent findings, or when the diff itself edits SPEC.md. A package with a short Tasks section (lines under 40 characters, or only one long line) will pass with the section present. Both the lines and the section parse are derived from the same function, so the check is only as reliable as that parse.
Fix: check structurally for `## Tasks` or `## Hints` headings in the spec region of the package. Alternatively, use the marker from the alternatives above.

4. [attention · 3] **`.agent/tools/review-findings.py:63`** — a generated-file path match is `endswith` on the `diff --git` line, and unmatched paths are silent
```
current = next((path for path in generated if line.endswith(f" b/{path}")), "")
```
A generated path of `a.lock` also matches `x/a.lock`, because the check is a suffix match on the header. This is a false positive. Renamed files and quoted paths (spaces) in a `diff --git` header do not match at all, so those hunks slip through. `generated` is also a set, so the iteration order is arbitrary when more than one path matches.
Fix: parse the header into the `b/` path exactly, with `line.split(" b/", 1)[1]` or the `+++` line, and compare it with `==`.

5. [nit · 3] **`.agent/tools/review-findings.py:40`** — the signature takes `mode` and `spec_path` for a spec that is optional, and a missing SPEC.md disables the check silently
Cost: with no SPEC.md at `owner/SPEC.md`, `builder_lines` is empty and the Tasks/Hints check is skipped with no notice. A misconfigured owner path would look like a clean pass.