Assessment: request-changes — the new `persist --strict` gate rejects review directories written before this change, with no way to tell old packages from broken ones, and it names a `spec-context` command I could not find.

Read beyond the package: `.agent/tools/review-findings.py` (the only file in the working directory; grep for the helpers and the `spec-context` subcommand).

1. [blocking · 4] **`.agent/tools/review-findings.py:94`** — strict persist retroactively fails review dirs packaged before this change
```
violations = package_violations(args.review_dir, args.personas, args.mode, owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
A review dir created by the previous orchestrator holds `<persona>.in.md` files that embed `diff.patch` (generated hunks included) and the full spec with Tasks/Hints. Persona runs that began before the upgrade, or a re-persist of an old dir, now raise `ValueError` at the very end. The reviewers' work is finished at that point and REVIEW.md is never written. Nothing separates a stale package from a broken one, and no version marker, flag or opt-out exists.
Fix: record a package-format version in the review dir, for example in `hunks.json` or a manifest. Enforce the gate only when the dir carries the new version. Alternatively, add a `--no-package-check` escape hatch and make it a warning for dirs without the marker.

2. [attention · 3] **`.agent/tools/review-findings.py:60`** — the error points at a `spec-context` subcommand I cannot find
```
"build its spec with `review-findings.py spec-context`"
```
This diff adds `spec_sections` but no `spec-context` parser or handler. The only grep hit for `spec-context` in the file is this message. If the subcommand does not exist elsewhere, the remediation text sends the operator to a command that fails, and the orchestrator has no tool to produce the filtered spec. The checker therefore enforces a rule that nothing in the diff can satisfy.
Fix: add the subcommand in this change, built on `spec_sections`, or confirm where it lives. Otherwise reword the message.

3. [attention · 3] **`.agent/tools/review-findings.py:44`** — a missing SPEC.md or non-code mode silently disables the Tasks/Hints check
```
if mode in CODE_MODES and spec_path and spec_path.is_file():
    builder_lines = {...}
```
`owner = args.review_dir.parent.parent` is a layout guess. If the spec sits elsewhere, `builder_lines` stays empty and a package carrying Tasks/Hints passes with no signal. In that case the guarantee, "a package that broke the rules cannot reach REVIEW.md", is false without anyone noticing.
Fix: emit a warning or error when the mode is a code mode, the spec is expected and the file is absent. Take the spec path from an explicit argument.

4. [attention · 3] **`.agent/tools/review-findings.py:47`** — the generated-file check depends on the hunks-index schema and on the diff path format
```
generated = {entry["path"] for entry in read_json_object(hunks_path, "files")["files"] if entry.get("generated")}
...
current = next((path for path in generated if line.endswith(f" b/{path}")), "")
```
The check couples `persist` to the `hunks.json` shape and to `git diff` header formatting. Quoted paths with special characters, renames and `--no-prefix` diffs would all evade the match. `read_json_object` and `canonical_personas` are not defined in this file, so I could not check their contracts, including whether `["files"]` is guaranteed to exist. The failure mode is a false pass, which is the weaker kind of gate, not a crash.
Fix: have `package.diff` generation write a manifest of the paths it collapsed. Compare against that manifest instead of re-deriving the set from diff text.

5. [nit · 3] **`.agent/tools/review-findings.py:58`** — the copied-lines heuristic uses an arbitrary threshold (`>= 2` lines of at least 40 characters)
A spec whose Tasks quote a long acceptance line would trip the check. A package with exactly one leaked Tasks line would pass. Cost: both false positives and false negatives are possible, and the threshold is hard to explain to an operator.