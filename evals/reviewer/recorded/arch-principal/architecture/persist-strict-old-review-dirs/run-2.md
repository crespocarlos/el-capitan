Assessment: request-changes — the packaging rules are enforced at the one persist gate that old and in-flight review directories also pass through, and the checks can't tell a copied spec from a legitimately quoted one.
Read beyond the package: `.agent/tools/review-findings.py` (persist body, grep for `spec-context` and the helpers)

Approach: redirect — Keep the trimming, but enforce it where the package is built, and make the persist-time check advisory or keyed to the package's provenance instead of re-deriving it from text.
Alternatives considered:
- Don't build the validator; rely on the orchestrator to trim the spec and embed `package.diff`. This is the smallest change. It loses because the stated risk is a silent regression, and a cheap check is justified. It wins on the cost of false positives and rollout.
- Have the builder write a manifest (`<persona>.in.meta.json` with spec variant, diff source and hashes), and have `persist --strict` check the manifest. This is the best alternative. It has one owner for the rule and no text-matching heuristics. It also lets old directories be told apart by a missing manifest. It costs a small writer step.
- The chosen approach, line-matching in `persist --strict`, is cheap and needs no new format. But it re-derives a fact from rendered text, and it hard-fails on stale artifacts.

Price of the next changes: adding another trimmed section (for example `## Notes`) or another full-spec persona means editing `SPEC_BUILDER_SECTION` and `SPEC_FULL_PERSONAS` here. The package builder has to be edited to match, and a `spec-context` command I could not find in this file has to agree with both. A manifest would make each of these one edit in the builder.

1. [attention · 4] **`.agent/tools/review-findings.py:94`** — `--strict` now hard-fails review directories built before this change
```
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
Any review directory whose `*.in.md` files embed `diff.patch` and the full spec raises `ValueError` on `persist --strict`. That covers reviews in flight at deploy time and old directories that get re-persisted. The failing check is a packaging rule, not a defect in the review output. The message also tells the user to rebuild packages the personas have already answered. Nothing limits this to new directories, and the old shape has no migration.
Fix: Gate it on a marker the new builder writes (a manifest or version field in `hunks.json`). Skip the check, or only warn, when the marker is absent. Alternatively, make this check a separate `check-packages` command that the orchestrator runs before dispatch.

2. [attention · 3] **`.agent/tools/review-findings.py:57`** — the "copied Tasks/Hints" check is a text heuristic, and it can be a false positive or a false negative
```
copied = builder_lines.intersection(line.strip() for line in lines)
if len(copied) >= 2:
```
A spec's Tasks or Hints lines of 40 or more characters can legitimately show up in a persona package. The diff may contain the same text, for example a spec edited in the same change, or a checklist line in a quoted file. Two such lines raise a hard error even though the persona never got the Tasks section. In the other direction, a wrapped or reformatted copy, or a single leaked line, passes. `spec_sections` also treats a fenced `## ` line as content, but `line.startswith("## ")` on the builder set is applied after `strip`, so an indented heading is not excluded.
Fix: Check provenance rather than text. Compare the spec block in the package to `spec_sections(spec)[0]` exactly, or use a manifest. If you keep the text check, scan only the spec block of the package, not the whole file.

3. [attention · 3] **`.agent/tools/review-findings.py:50`** — generated-file detection depends on the `hunks.json` schema and is checked by path suffix
```
generated = {entry["path"] for entry in read_json_object(hunks_path, "files")["files"]
             if entry.get("generated")}
...
current = next((path for path in generated if line.endswith(f" b/{path}")), "")
```
`"files"` is read by subscript, so a `hunks.json` without that key raises `KeyError`, not the `ValueError` that `persist` callers expect. The `endswith(" b/path")` match is also ambiguous. Generated `a/x.lock` and a real `sub/a/x.lock` can collide, and renames, quoted paths and the `/dev/null` forms for adds and deletes are missed. A hunk of a generated file can then be missed, or a real file's hunks can be flagged.
Fix: Use `.get("files", [])` or the validator `read_json_object` already provides. Parse the `diff --git a/X b/Y` header into exact paths and compare for equality.

4. [needs more info · 2] **`.agent/tools/review-findings.py:60`** — the error message names `review-findings.py spec-context`, and I could not find that subcommand
The excerpt defines no `spec-context` subcommand. `spec_sections` is defined but only called by `package_violations`, so no builder uses it. If the subcommand lives elsewhere, this is fine. If it doesn't exist, the gate tells the operator to run a command that fails, and the "right" package can't be built by the documented path. The question is whether the orchestrator's builder and `spec_sections` share this code. If they don't, the split rule has two owners and will drift.

Handoff to adversarial: `.agent/tools/review-findings.py:35` — `in_fence` toggles on any line starting with three backticks, so a four-backtick fence or an unclosed fence misclassifies later sections.