Assessment: request-changes — the new `--strict` gate points authors at a `spec-context` command that doesn't exist, and it also fails every older review directory.

Read beyond the package: `.agent/tools/review-findings.py` (the whole file as present in the working directory).

1. [blocking · 4] **`.agent/tools/review-findings.py:60`** — the gate's remedy names a `spec-context` subcommand that doesn't exist (h1)
```
errors.append(f"{package.name} carries the spec's Tasks/Hints ({len(copied)} lines); "
              "build its spec with `review-findings.py spec-context`")
```
A grep for `spec-context` finds only this message. `spec_sections` is a library function and nothing exposes it on the CLI. The orchestrator therefore has no supported way to build a spec without Tasks and Hints. It either hand-trims the spec or can't pass `--strict`. The size reduction this change is for depends on that command existing.
Fix: add the `spec-context` subcommand, which prints the `kept` lines of `spec_sections`, and have the orchestrator call it. Or drop the reference from the message and name the real mechanism.

2. [blocking · 3] **`.agent/tools/review-findings.py:91`** — `--strict` now rejects review directories built before this change
```
if args.strict:
    ...
    violations = package_violations(args.review_dir, ...)
    if violations:
        raise ValueError("; ".join(violations))
```
Any existing review directory has `<persona>.in.md` files that embed `diff.patch`, with hunks of generated files and the full spec. If `persist --strict` is rerun on one, it fails before `REVIEW.md` is written. That is a retroactive failure of a persisted artifact, and the same applies to a rerun mid-rollout, when the orchestrator hasn't switched to `package.diff` yet. The release also has no flag to turn the gate off, and the only way back is to revert.
Fix: gate on a package-format marker, such as a version field in `hunks.json` or a header in `.in.md`, and skip packages without it. Or add an explicit `--no-package-check` escape hatch, and ship the orchestrator change before the gate.

3. [attention · 3] **`.agent/tools/review-findings.py:41`** — the generated-file check depends on a `generated` field and a `files` key that older `hunks.json` files may lack
```
generated = {entry["path"] for entry in read_json_object(hunks_path, "files")["files"]
             if entry.get("generated")}
```
If a `hunks.json` was written before `generated` existed, `entry.get("generated")` is falsy for every entry. The check then passes silently for packages that do embed generated hunks. If `files` or `path` is missing, the function raises a `KeyError` that isn't a `ValueError`. Two components, the hunk writer and this reader, share a schema with no version. Pre-existing for the schema; this change adds the reader.
Fix: have the hunk writer own a schema version. Treat a missing `generated` field as "unknown" and report that rather than passing.

4. [attention · 3] **`.agent/tools/review-findings.py:47`** — the Tasks/Hints leak detection is heuristic, and a second copy of the fact stays on disk
```
copied = builder_lines.intersection(line.strip() for line in lines)
if len(copied) >= 2:
```
The rule "non-product-flow personas don't see Tasks/Hints" lives in `spec_sections` for building, and again as an exact-line match for checking. Short lines under 40 characters are ignored, and any reflow or rewrapping defeats the match. A package with a single copied long line also passes. Detecting a violation after the fact is weaker than enforcing the rule where the package is built.
Fix: make the builder the single owner. Have it record in the package a marker such as `spec: context` or `spec: full`, and have the checker verify that marker against the persona.