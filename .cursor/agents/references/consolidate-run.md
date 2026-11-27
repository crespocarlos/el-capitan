# Consolidation commands

The mechanical half of `crew-reviewer` Step 7. [Consolidation](~/.cursor/agents/crew-reviewer/references/consolidation.md)
decides what is kept; these tool calls build the files from it, so no `candidates.json`, anchor or
numbered list is typed by hand. `REVIEW_ROOT` is the review directory.

1. Save the kept candidates (the contract's finding shape, one object each, with `file`, `line` and
   `kind`) as `$REVIEW_ROOT/raw-candidates.json`.
2. `~/.agent/bin/crew-review-findings.py consolidate --review-dir "$REVIEW_ROOT"` groups candidates
   with the same file, the same `kind` and overlapping lines, fills hunk ids from `hunks.json` and
   writes the draft `candidates.json`. It never rewrites a title or a label; edit the draft if you
   disagree with a group.
3. `~/.agent/bin/crew-review-findings.py normalize "$REVIEW_ROOT/candidates.json" --hunks
   "$REVIEW_ROOT/hunks.json" --files <changed paths> --repo <repo root> --head <reviewed head sha>
   --output "$REVIEW_ROOT/consolidation.json"`. `--repo` and `--head` let a finding about a tracked
   file outside the diff stand as a non-hunk anchor (a `[blocking]` one needs `line_read: true`); an
   untracked path is refused. A hand-set `anchor` in the input is ignored.
4. `~/.agent/bin/crew-review-findings.py consolidate --review-dir "$REVIEW_ROOT" --render --mode
   <mode>` writes `report.md` from `consolidation.json`: the numbered list `persist` compares to the
   findings. Reply with that file, then persist per [pipeline
   persistence](~/.cursor/agents/crew-reviewer/references/pipeline.md).
