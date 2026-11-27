Assessment: approve — the change fixes the crash on a nit with no evidence. It also lets non-string evidence skip the reviewed-file check.
Read beyond the package: none (a grep of the working directory found only this file, with no tests or other callers).

1. [attention · 3] **`.agent/tools/review-findings.py:27`** — the guard also skips the file-set check for non-string evidence
```python
if files and isinstance(evidence, str) and evidence:
```
The crash came from `evidence` being `None`. The `isinstance` test is wider than that: a `nit`, `concern` or `needs more info` finding whose evidence is a list, a dict or a number now skips the reviewed-file check without any error. Only `blocking` and `attention` findings are type-checked above. A nit with `evidence: ["untouched.py:3"]` therefore passes `--strict --files`, although the check exists to reject citations outside the reviewed set. The new comment says only that a finding with no evidence is allowed.
Fix: skip only for a missing value, with `if files and evidence not in (None, ""):`. Then reject a non-string value with a `ValueError` that names the finding title, or let `.split` fail loudly.

2. [attention · 3] **`.agent/tools/review-findings.py:27`** — no test covers the new skip branch
```python
if files and isinstance(evidence, str) and evidence:
```
I found no tests in the working directory. The crash regression (a nit with no evidence under `files`) is easy to reintroduce. Nothing would catch someone reverting to `if files:`. Nothing would catch the loophole in finding 1 either. The tests need cases for evidence that is missing, empty and non-string, plus one case where a nit cites a file outside `files` and must still be rejected.
Fix: add a small table test for `check_strict(..., files=[...])` covering those four inputs. Put it in the existing test module for this tool.