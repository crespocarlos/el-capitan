Assessment: request-changes — the new strict gate rejects review directories packaged before this change, and its error message points to a `spec-context` command that this file does not define.
Read beyond the package: `.agent/tools/review-findings.py` (full excerpt). It is the only file in the working directory, so I could not check the orchestrator or other consumers.

1. [blocking · 3] **`.agent/tools/review-findings.py:60`** — The gate's remedy names a `spec-context` subcommand that does not exist in this tool
```
errors.append(f"{package.name} carries the spec's Tasks/Hints ({len(copied)} lines); "
              "build its spec with `review-findings.py spec-context`")
```
A grep of the working directory finds `spec-context` only in this message. `spec_sections` is a helper with no CLI entry point in the excerpt. If the orchestrator has no way to produce the stripped spec, a strict persist fails on any package that embeds the full spec. The orchestrator then has no documented way to pass the gate. I only see an excerpt, so the subcommand may live in the unshown part of the file, which is why this is 3.
Fix: add the `spec-context` subcommand, which should call `spec_sections` and print the kept lines. Otherwise change the message to name a command that exists. Ship the subcommand and the gate together.

2. [attention · 4] **`.agent/tools/review-findings.py:94`** — The new strict gate fails old review directories with no migration or opt-out
```
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
A review directory packaged before this change embeds `diff.patch` with generated-file hunks and the full spec. Running `persist --strict` on it now raises, so the report cannot be written. The only way past it is to repackage and re-dispatch every persona. Strict was previously a hunk-ref check on findings, so it now also gates how packages were built. That is a contract change for existing callers of `--strict`. Revert is possible only by dropping the flag, and that also drops the hunk-ref check.
Fix: put the package gate behind its own flag, or a package-format marker such as a version line in `<persona>.in.md`. Skip the check for packages that lack the marker.

3. [attention · 3] **`.agent/tools/review-findings.py:46`** — The spec-copy detector can miss a spec that has been stripped or reformatted
```
builder_lines = {line.strip() for line in spec_sections(...)[1]
                 if len(line.strip()) >= SPEC_LINE_MIN and not line.startswith("## ")}
...
if len(copied) >= 2:
```
Two facts are owned separately. `spec_sections` decides what counts as a builder section, and the checker re-derives that from the spec's text. The check needs the file `owner / "SPEC.md"` to exist. In modes outside `CODE_MODES`, or after the spec is moved or edited, `builder_lines` is empty and the check passes silently. A package that embeds the full spec then goes through. Tasks written as short lines under 40 characters or as wrapped lines also pass. The detector is a heuristic that guards a structural rule.
Fix: have the orchestrator write a marker or hash of the stripped spec, and check that instead of matching lines. At minimum, log when the check is skipped for lack of `SPEC.md`.

4. [attention · 3] **`.agent/tools/review-findings.py:63`** — Generated-file detection matches paths by suffix and only on `diff --git` headers
```
current = next((path for path in generated if line.endswith(f" b/{path}")), "")
```
`generated` holds repo-relative paths from `hunks.json`. If a generated file `x/a.lock` is flagged and a non-generated file `y/x/a.lock` also appears, the suffix match is ambiguous and may flag the wrong file. A renamed or quoted path, such as one with spaces, never matches, so the embedded hunks slip through. The package format is parsed with string matching instead of using the hunk index it already has.
Fix: compare `line.split(" b/", 1)[1]` for equality with the path, and handle quoted paths.