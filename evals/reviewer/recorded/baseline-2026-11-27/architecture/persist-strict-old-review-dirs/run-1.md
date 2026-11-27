Assessment: request-changes — the new `--strict` gate points at a `spec-context` subcommand that doesn't exist, and it will reject every review directory built before this change.

1. [blocking · 4] **`.agent/tools/review-findings.py:60`** (h2) — the error message names a subcommand that this change doesn't add
```
errors.append(f"{package.name} carries the spec's Tasks/Hints ({len(copied)} lines); "
              "build its spec with `review-findings.py spec-context`")
```
`spec_sections` is added, but nothing exposes it as a `spec-context` subcommand. My grep of the working tree for `spec-context` found only this message string. The orchestrator therefore has no supported way to build a filtered spec. A `--strict` failure sends the user to a command that isn't there, and the only recovery is to hand-edit the packages.
Fix: add the `spec-context` subcommand, which would print the kept lines of `spec_sections(spec)` for non-product-flow personas. If it already lives in a file I couldn't see, say so and drop this finding.

2. [attention · 4] **`.agent/tools/review-findings.py:94`** (h3) — the new strict gate breaks re-running `persist` on existing review directories
```
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
The module docstring says `persist` can be re-run on the same directory and produce the same report. Any review directory built before this change has full-spec packages that embed `diff.patch`. Re-running `persist --strict` on one now raises, even though the findings are unchanged. The `persist` path is also the only one that checks these rules, and a violation can't be bypassed or downgraded to a warning. Packaging is a property of how the packages were built, not of the report, so it is coupled to the persist step.
Fix: apply the gate only to review directories created after the change, for example by recording a package-format marker in `hunks.json`. Alternatively, make it a warning on directories without the marker, or add an explicit opt-out flag.

3. [attention · 3] **`.agent/tools/review-findings.py:55`** (h2) — the copied-spec detection is fragile
```
copied = builder_lines.intersection(line.strip() for line in lines)
if len(copied) >= 2:
```
The check passes only if two or more stripped task lines of at least 40 characters appear verbatim in the package. A persona package can legitimately contain those lines. The diff may touch the SPEC itself, or a finding may quote a Task line. The gate would then reject a correct package. A re-wrapped or reformatted spec copy would slip through. The heuristic is also tied to the markdown rendering of the spec rather than to a marker the builder writes.
Fix: have the package builder emit a sentinel, such as a header line naming the spec variant. The gate would check for that sentinel instead of matching line content.

4. [nit · 3] **`.agent/tools/review-findings.py:60`** (h2) — `hunks.json` is parsed by `read_json_object` in two places, which couples the gate to its schema
`package_violations` reads `entry["path"]` and `entry.get("generated")` directly. `check_hunk_refs` and `hunk_ids` also read the same file, so a change to the schema now has two readers to update.
Fix: add a helper next to `hunk_ids` that returns the set of generated paths, so the schema is read in one place.