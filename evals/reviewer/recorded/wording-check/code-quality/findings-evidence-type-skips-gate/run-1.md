Assessment: request-changes — the crash is fixed, but the new guard also skips the reviewed-file gate for evidence of the wrong type, and no test covers either case.

Read beyond the package: none (I grepped the working directory for other users of `check_strict` and `evidence`; there are none, and no test file exists).

1. [attention · 4] **`.agent/tools/review-findings.py:27`** — The guard waves through non-string evidence instead of rejecting it
```python
if files and isinstance(evidence, str) and evidence:
```
   The fix means to skip only findings with no evidence, but `isinstance(evidence, str)` also skips any other type. A nit, `needs more info` or `concern` finding with `evidence=["other.py:3"]` or `evidence=42` now passes `--strict --files` unchecked. Before the change it crashed. The comment says "no evidence", so a reader will think malformed evidence is still caught. `EVIDENCE_LOCATION` is only enforced for `blocking` and `attention`, so nothing else catches it.
   Fix: skip only when evidence is missing (`if files and evidence is not None and evidence != ""`). Then raise a `ValueError` if it is not a `str`, or treat it as no evidence only on purpose and say so in the comment.

2. [attention · 4] **`.agent/tools/review-findings.py:27`** — The fix has no regression test, and the new branch is untested
```python
if files and isinstance(evidence, str) and evidence:
```
   The repository has no test file for `check_strict`. A revert to `if files:` would bring the AttributeError back unnoticed. Nothing checks the other side either: an unanchored nit passes, while a nit citing an unreviewed file still raises "not in the reviewed file set". Without that second case, a guard that skips every nit would also pass.
   Fix: add a small table-driven test of `check_strict` with `files=["a.py"]`. Cases: nit with no `evidence` key passes; nit with `evidence=None` passes; nit with `evidence="b.py:3"` raises; nit with `evidence="a.py:3"` passes; non-string evidence behaves as decided in finding 1.