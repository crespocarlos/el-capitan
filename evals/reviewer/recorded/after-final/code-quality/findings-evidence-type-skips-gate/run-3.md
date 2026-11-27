Assessment: approve — the guard fixes the AttributeError on a nit with no evidence, and the gate still holds for blocking and attention findings. It has no regression test.

Read beyond the package: `.agent/tools/review-findings.py` (full file), plus a grep for `check_strict` and `evidence` across the working directory. Only that one file matched, so no tests exist.

1. [attention · 4] **`.agent/tools/review-findings.py:27`** — The None-evidence fix has no regression test.
```python
        if files and isinstance(evidence, str) and evidence:
```
A grep for `check_strict` and `evidence` finds no test file. A later revert to `if files:` would bring back the crash on a nit with no evidence, and nothing would fail. The new guard also has branches that only a test can pin: missing, empty and non-string evidence skip the check, while a string citing an unreviewed file must still raise.
Fix: add a table-driven test of `check_strict(findings, files=[...])` with these cases:
- a nit without evidence passes;
- a nit with `evidence=""` passes;
- a nit citing `other.py:3` raises the "not in the reviewed file set" error;
- an attention finding citing a reviewed file passes.

2. [nit · 3] **`.agent/tools/review-findings.py:27`** — Non-string evidence on a non-blocking finding skips the file-set gate without a signal.
```python
        if files and isinstance(evidence, str) and evidence:
```
A nit or `needs more info` finding with `evidence=["unreviewed.py:9"]` or `42` is neither shape-checked nor checked against the reviewed file set. The comment only explains the missing-evidence case. The cost is that a malformed anchor on a nit goes through unflagged. If that is intended, say so in the comment. Otherwise raise on `evidence is not None and not isinstance(evidence, str)`.