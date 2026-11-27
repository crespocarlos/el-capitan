Assessment: approve — the guard fixes the AttributeError on a nit with no evidence. `blocking` and `attention` findings are already forced to carry string evidence earlier in the loop, so skipping the file check when evidence is absent loses no coverage.

1. [attention · 4] **`.agent/tools/review-findings.py:27`** — no regression test for the crash this fixes
```python
        if files and isinstance(evidence, str) and evidence:
```
A grep for `check_strict` across the working directory matches only this file, so no test exercises it. The crash was a `--strict --files` run on a nit without `evidence`. Nothing stops `evidence=None` or a missing key from regressing. A test would also pin the neighbouring case: a nit with evidence outside `files` must still raise.

Fix: add a test that calls `check_strict([{"label": "nit", "title": "t", "disposition": "patch"}], files=["a.py"])` and asserts it does not raise. Add a second case with `evidence="b.py:3"` and `files=["a.py"]` that asserts `ValueError`. Put both in the existing test module for this tool, or state why a new file is needed.

2. [nit · 3] **`.agent/tools/review-findings.py:27`** — non-string evidence on a nit passes the gate silently
```python
        if files and isinstance(evidence, str) and evidence:
```
A nit with truthy non-string evidence, such as a list or dict, skips the reviewed-file check. It is never reported as malformed, because the shape check at line 17 only covers `blocking` and `attention`. A malformed anchor on a nit then reads as "no anchor", which makes producer bugs hard to spot. This is a small cost, since the nit is unanchored either way.

Fix: split the cases. Skip only when `evidence is None` or `evidence == ""`. Raise `ValueError` when evidence is present but not a `str`.