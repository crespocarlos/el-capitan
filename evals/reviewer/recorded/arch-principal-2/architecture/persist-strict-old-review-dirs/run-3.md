Assessment: request-changes — the package-size cut is the right idea, but the strict gate rejects review directories built before this change, and its error tells the user to run a `spec-context` subcommand that I could not find.

Read beyond the package: `.agent/tools/review-findings.py` (header and `persist`), plus a repo-wide grep for `spec-context` and `.in.md`.

Approach: redirect — trimming the package at build time is right, but a post-hoc text-matching gate in `persist --strict` is the wrong enforcement point, because it makes old directories unpersistable and copies the spec's rules into a second place.
Alternatives considered:
- Build-time guarantee only: have `spec-context` and the orchestrator emit the trimmed spec and `package.diff`, and record in a manifest which spec and diff each package used. `persist` would check the manifest rather than re-parse prose. This is more robust and doesn't depend on a 40-character, 2-line coincidence heuristic, so I prefer it.
- Don't build the gate (the trimming alone): this leaves nothing to catch an orchestrator that regresses to `diff.patch` and silently re-inflates packages. That part of the need is real, so the gate is worth keeping in some form, just not as this one.
- Gate as built, but conditional on a version marker: a cheaper middle path that keeps the check and fixes the old-directory problem (finding 1).

1. [blocking · 4] **`.agent/tools/review-findings.py:94`** (h1) — `--strict` now fails on every review directory created before this change
```
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
The module docstring says `persist` "can be re-run on the same directory after a partial failure and produces the same report". An in-flight review directory has `<persona>.in.md` files with Tasks/Hints and `diff.patch` hunks, because it was packaged by the old orchestrator. Re-running `persist --strict` on it raises `ValueError` and the report is never written. The only way out is to rebuild every package, which re-dispatches the personas. Nothing in the diff versions the packages, so old and new directories can't be told apart.
Fix: write a package-format marker (for example a `package_version` field in `hunks.json` or a manifest) when packaging, and have `package_violations` skip, or only warn on, directories without it. Alternatively, warn instead of raising for directories whose `hunks.json` predates the change.

2. [attention · 3] **`.agent/tools/review-findings.py:60`** — the error points at a `spec-context` subcommand I could not find
```
"build its spec with `review-findings.py spec-context`")
```
Grep over the working directory finds `spec-context` only in this string. The diff shows no subcommand, and the file is an excerpt, so it may exist elsewhere. If it doesn't, the user who hits this violation has no tool that produces a conforming spec. The only trimming logic is `spec_sections`, which has no CLI entry point in this diff. The orchestrator also has to call `spec_sections` for the trim and not just the gate, and the diff doesn't show that either.
Fix: add the `spec-context` subcommand, backed by `spec_sections`, in this change. Otherwise name the real entry point in the message.

3. [attention · 3] **`.agent/tools/review-findings.py:57`** — the Tasks/Hints leak detector is a heuristic that gives both false positives and false negatives
```
copied = builder_lines.intersection(line.strip() for line in lines)
if len(copied) >= 2:
```
The same spec facts are kept in two places: the split in `spec_sections` and a re-derivation here that matches stripped lines of at least 40 characters. A persona package that quotes the diff, or an acceptance criterion that repeats a task line verbatim, will match twice and block persist. A trimmed package that still carries one long Tasks line, or a reflowed one, will pass. Hints headings like `## Tasks (v2)` also depend on the `\b` regex, so the two sides can disagree on what a builder section is.
Fix: record in the manifest which spec variant each package used (full or trimmed) and check that. Or at least match against the output of one shared function.

4. [attention · 3] **`.agent/tools/review-findings.py:46`** — the generated-file check passes silently when `hunks.json` has no `generated` flag
```
if entry.get("generated")}
```
An older `hunks.json` without a `generated` key makes `generated` empty. Then the diff check passes vacuously, so the strict gate reports success when it checked nothing. Also, `read_json_object(...)["files"]` raises `KeyError` for a `hunks.json` with no `files` key, which `persist` reports as a crash instead of a violation.
Fix: treat a missing `generated` key as unknown and say so, using `.get("files", [])`. This falls out of the version marker in finding 1.

5. [nit · 3] **`.agent/tools/review-findings.py:94`** — the spec location is derived from the directory layout
```
owner / "SPEC.md"
```
`owner = args.review_dir.parent.parent` assumes a fixed layout. If the layout differs, `spec_path.is_file()` is false and the Tasks/Hints check is skipped with no message. The strict gate then does less than it appears to.
Fix: accept an explicit `--spec` path, or report that the spec was not found when the mode is a code mode.

Next changes and their cost:
- A new section to trim, such as "Notes": this means editing `SPEC_BUILDER_SECTION`, and the leak heuristic follows automatically. A different set of personas per section would need a new mapping.
- A new generated-file class: this is cheap, because the flag comes from `hunks.json`.
- Changing the package layout: this is expensive under the current design, because the gate parses the text of every `.in.md`. A manifest would make it cheap.