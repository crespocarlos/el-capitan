Assessment: request-changes — the validator tells the operator to run a `spec-context` command that doesn't exist, and the diff doesn't contain the embed-`package.diff` change it says it enforces.

Read beyond the package: `.agent/tools/review-findings.py` (grep for `spec-context`, `canonical_personas`, `read_json_object` and the imports)

Approach: redirect — Enforce the packaging rules where the packages are built, and keep `persist` as a cheap backstop. A post-hoc string-matching audit inside `persist --strict` is the wrong primary mechanism.
Alternatives considered:
- Build packages with one shared function (`spec_sections` plus a `package.diff` builder) and have `persist` compare against a manifest of what was embedded. This wins. The rule then has one owner and nothing is re-derived by line matching. The cost is a small manifest file written at build time.
- Don't validate at all and rely on the orchestrator prompt. It loses, because the prompt already drifted: 156 KB packages were being sent. A cheap check is justified, but it should check a recorded fact, not infer one.
- The chosen approach: a line-intersection heuristic inside `persist --strict`. It is cheap, but it has two owners for the "what is a builder line" rule and it gates the report on a heuristic.

1. [blocking · 4] **`.agent/tools/review-findings.py:60`** — the error message points to a command that doesn't exist
```
"build its spec with `review-findings.py spec-context`")
```
The only `spec-context` match in the tool is this message. The diff adds `spec_sections` as a function but registers no subcommand for it. A package that carries Tasks/Hints fails `persist --strict`, and the operator is told to run a command that doesn't exist. The orchestrator has no tool to build the spec-minus-builder-sections text, so the rule can't be followed. Nothing in the diff shows how packages are built with `package.diff`. If that is done by prompt only, the check enforces a rule that has no implementation.
Fix: add a `spec-context` subcommand that prints `spec_sections(spec)[0]`, and wire the orchestrator to use it. Alternatively, reword the message to name what actually exists.

2. [attention · 4] **`.agent/tools/review-findings.py:94`** — `--strict` now fails on any older review dir
```
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
Any review directory built before this change embeds `diff.patch` with generated-file hunks and the full spec. Re-running `persist --strict` on it now raises, and `ValueError` is a hard failure with no reviewable report. The check also validates the package inputs, not the findings being persisted. A user who only wants to persist findings from a finished review is blocked.
Fix: apply the check only when the dir is marked as built by the new packager, for example through a manifest field or version. Otherwise print the violations as warnings unless `--strict-packages` is passed.

3. [attention · 3] **`.agent/tools/review-findings.py:57`** — "Tasks/Hints" detection is a second derivation that can disagree with the packager
```
copied = builder_lines.intersection(line.strip() for line in lines)
if len(copied) >= 2:
```
A fact with two owners: the packager decides what to strip, and the validator re-derives it by exact-line matching with a 40-character floor and a count of at least 2. A spec whose Tasks are short bullets, or a single long Tasks line, passes silently. A task line that legitimately appears in the diff (a spec quoted in a file under review, or `SPEC.md` itself in the diff) falsely fails the package. Product-flow is exempt, but every other lens is exposed to the false positive.
Fix: have the packager record the sections it removed in a manifest and check against that. Otherwise skip lines that sit inside diff hunks.

4. [attention · 3] **`.agent/tools/review-findings.py:51`** — `canonical_personas` and `read_json_object` are used but neither defined nor imported in this file
```
for persona in canonical_personas(personas, split_commas=False):
generated = {entry["path"] for entry in read_json_object(hunks_path, "files")["files"]
```
The visible imports are only `argparse`, `re` and `pathlib`. Line 84 already used `canonical_personas`, so it is probably defined elsewhere in the file. I couldn't verify either helper, or the shape of `files` in `hunks.json` (`entry["path"]` and `generated`). A `KeyError` there would break `persist --strict` for every dir that has hunks.
Fix: confirm the helpers and the `hunks.json` schema, and use `entry.get("path")`.

5. [nit · 3] **`.agent/tools/review-findings.py:66`** — the generated-file matching has an edge case
`line.endswith(f" b/{path}")` also matches a different file whose path ends in the same suffix, such as `x/b/a.lock` against `a.lock`. The result is a false violation, and the cost is a confusing error. Compare the exact `b/` path instead.