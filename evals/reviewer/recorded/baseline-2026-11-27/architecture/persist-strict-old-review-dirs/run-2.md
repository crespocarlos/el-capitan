Assessment: request-changes — `persist --strict` now enforces a packaging rule on every review dir, including ones built before the rule existed. The change also relies on helpers and a subcommand I could not find in the working directory.

1. [blocking · 3] **`.agent/tools/review-findings.py:94`** — strict persist retroactively fails review dirs packaged before this change
```python
violations = package_violations(args.review_dir, args.personas, args.mode,
                                owner / "SPEC.md", hunks_path)
if violations:
    raise ValueError("; ".join(violations))
```
`--strict` previously checked only hunk refs. It now also rejects any `<persona>.in.md` that embeds generated-file hunks or carries Tasks/Hints. Review dirs created before this change (in-flight reviews, or re-persists of old dirs) contain exactly those packages. Their `persist --strict` will fail, and the packages can't be fixed without re-dispatching every persona. The contract change for existing callers has no gate or migration. The check also can't tell a package built by the old orchestrator from one built wrongly by the new one.
Fix: gate the check on a marker the new orchestrator writes, such as a package-version line or a `package.diff` file in the review dir. Alternatively, make it opt-in (`--check-packages`) or emit warnings for old dirs.

2. [attention · 3] **`.agent/tools/review-findings.py:61`** — the violation check is a heuristic and couples `persist` to the package text layout
```python
current = next((path for path in generated if line.endswith(f" b/{path}")), "")
...
copied = builder_lines.intersection(line.strip() for line in lines)
if len(copied) >= 2:
```
Detection scans rendered markdown for `diff --git` lines and for verbatim spec lines of 40 or more characters. A hard `ValueError` depends on that scan. Two Tasks lines quoted legitimately in a finding or in the diff (for example, the spec file itself is changed) would block persist. A generated path that is a suffix of another path, such as `a.lock` and `sub/a.lock`, will also false-match. The orchestrator knows what it embedded, so the rule belongs in packaging, not in a text re-scan at persist time.
Fix: have the packager write a manifest, such as `<persona>.in.json` listing the diff source and spec variant. Have `package_violations` validate the manifest instead of scanning text.

3. [needs more info · 2] **`.agent/tools/review-findings.py:46`** — the `spec-context` subcommand, `canonical_personas`, `read_json_object` and `owner` are not verifiable
My grep found `spec-context` only inside the error string. I found no definition of `canonical_personas` or `read_json_object`, and `owner` (line 73) is set only inside `persist`. If `spec-context` doesn't exist, the error message points users at a command that fails. If `owner` is wrong for non-`.agent`-layout review dirs, `SPEC.md` silently resolves to a missing file and the Tasks/Hints check is skipped. Which file defines these, and does `spec-context` exist? If it doesn't, the remediation is a dead end and strict persist is unfixable by users.