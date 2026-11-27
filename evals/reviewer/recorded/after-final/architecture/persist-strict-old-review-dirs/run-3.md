Assessment: request-changes — the gate's error message tells the operator to run a command I found nowhere in the tool, and the check fails closed on review dirs written before this change.
Read beyond the package: `.agent/tools/review-findings.py` (persist, lines 68-101); grep for `spec-context`, `package_violations` and `canonical_personas` across the working directory.

1. [attention · 4] **`.agent/tools/review-findings.py:60`** (h1) — The remedy names a `spec-context` subcommand that I found nowhere in the tool
```
errors.append(f"{package.name} carries the spec's Tasks/Hints ({len(copied)} lines); "
              "build its spec with `review-findings.py spec-context`")
```
The only occurrence of `spec-context` in the working directory is this message. `spec_sections` is a library function with no CLI entry point in the excerpt. If the subcommand lives outside the excerpt, the orchestrator has two owners for the "which spec lines does a persona get" rule, one in the orchestrator prompt and one here. If it doesn't exist, the gate blocks and the operator is told to run a command that fails.
Fix: add the `spec-context <persona>` subcommand that calls `spec_sections` and the `SPEC_FULL_PERSONAS` rule, and have the orchestrator build packages with it. That leaves one owner for the rule and one for the check.

2. [attention · 4] **`.agent/tools/review-findings.py:94`** (h2) — `--strict` now fails on any review dir built before this change, with no bypass
```
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
A review dir produced by the previous orchestrator embeds `diff.patch` and the full spec, so every non-product-flow `*.in.md` carries Tasks/Hints. Re-running `persist --strict` on it, for example after a crashed persist or when persisting in-flight reviews during rollout, raises and writes no REVIEW.md. That is fine for new runs. For old dirs the only way out is to hand-edit the written packages, which falsifies the evidence the gate exists to protect. There is also no version marker to tell old dirs from new ones.
Fix: apply the gate only when the dir records the new packaging (for example a `package_version` field in `hunks.json`), or add an explicit `--allow-legacy-packages` escape hatch. Deploy the orchestrator change before the gate.

3. [attention · 3] **`.agent/tools/review-findings.py:48`** (h1) — The generated-file check depends on a `generated` flag that old `hunks.json` files lack, and fails open when it is absent
```
generated = {entry["path"] for entry in read_json_object(hunks_path, "files")["files"]
             if entry.get("generated")}
```
`hunks.json` written by an older producer has no `generated` key, so the set is empty and the check passes silently. In that case a package that embeds generated hunks gets through the gate. The schema also gains a field that nothing in the diff versions or documents. Separately, `owner / "SPEC.md"` is derived from `review_dir.parent.parent`. If the layout differs, `spec_path.is_file()` is false and the Tasks/Hints check is skipped with no signal.
Fix: warn or fail when `hunks.json` lacks the `generated` key under `--strict`, and when `SPEC.md` is missing in a code mode. Document the `generated` field with the `hunks.json` schema.

4. [nit · 3] **`.agent/tools/review-findings.py:20`** — The Tasks/Hints detector is a heuristic that duplicates the splitter's rules
The gate matches lines of 40 or more characters that appear in both the spec's builder section and the package, and needs 2 of them. Shorter task bullets are never checked. A package that includes the spec's Tasks heading but only short bullets passes. Verifying through `spec_sections` output on the package's embedded spec block would be less lossy. The cost is a gate that looks stricter than it is.